import logging
import time
import random
from googleapiclient.errors import HttpError
from src.config import ROLE_MAP
from src.batch_handler import execute_requests_in_batches

def list_files_recursively(drive_service, folder_id, current_path="", max_retries=5):
    """
    Recursively lists all files and folders under a folder ID with robust retry logic.
    """
    all_items = []
    page_token = None
    try:
        root_folder = drive_service.files().get(fileId=folder_id, fields='name').execute()
        current_path = f"{current_path}/{root_folder.get('name', 'Unknown')}"
    except HttpError as e:
        logging.error(f"Could not retrieve metadata for folder ID {folder_id}: {e}")
        return []

    while True:
        retries = 0
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            fields = 'nextPageToken, files(id,name,mimeType)'
            response = drive_service.files().list(q=query, fields=fields, pageSize=1000, pageToken=page_token).execute()
            
            files = response.get('files', [])
            for item in files:
                item['path'] = f"{current_path}/{item.get('name', 'Untitled')}"
                all_items.append(item)
                if item.get('mimeType') == 'application/vnd.google-apps.folder':
                    all_items.extend(list_files_recursively(drive_service, item['id'], current_path=current_path))
            
            page_token = response.get('nextPageToken')
            if not page_token:
                break
            
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504] and retries < max_retries:
                wait = (2 ** retries) + random.random()
                logging.warning(f"File list for {folder_id} failed with status {e.resp.status}. Retrying in {wait:.1f}s... ({retries + 1}/{max_retries})")
                time.sleep(wait)
                retries += 1
            else:
                logging.error(f"Failed to list files for folder {folder_id} after {max_retries} retries: {e}")
                break # Exit loop on persistent error
    return all_items

def get_report_for_items(drive_service, item_ids, progress_callback=None):
    """
    Generates a permission report for a specific list of item IDs using efficient batching.
    Returns the report data and a count of items that failed due to errors.
    """
    total_items = len(item_ids)
    error_count = 0
    logging.info(f"Preparing to fetch data for {total_items} items using batch requests...")
    if progress_callback:
        progress_callback(0, total_items * 2) 

    metadata_requests = [
        drive_service.files().get(fileId=item_id, fields='id,name,mimeType,owners,webViewLink,parents,copyRequiresWriterPermission')
        for item_id in item_ids
    ]
    logging.info("Executing batch request for file metadata...")
    metadata_results = execute_requests_in_batches(drive_service, metadata_requests, 
        lambda current, total: progress_callback(current, total * 2) if progress_callback else None)

    permission_requests = [
        drive_service.permissions().list(fileId=item_id, fields='permissions(id,type,emailAddress,domain,role)')
        for item_id in item_ids
    ]
    logging.info("Executing batch request for permissions...")
    permission_results = execute_requests_in_batches(drive_service, permission_requests,
        lambda current, total: progress_callback(total_items + current, total * 2) if progress_callback else None)

    report_data = []
    for i, item_id in enumerate(item_ids):
        item = metadata_results[i]
        permissions_response = permission_results[i]

        if not item or not permissions_response:
            logging.error(f"Could not retrieve full data for item ID {item_id}, skipping.")
            error_count += 1
            continue

        is_restricted = "N/A"
        if item.get('mimeType') != 'application/vnd.google-apps.folder':
            is_restricted = item.get('copyRequiresWriterPermission', False)

        owner = item.get('owners', [{}])[0].get('emailAddress', 'N/A')
        permissions = permissions_response.get('permissions', [])

        if not permissions:
            report_data.append({
                'Full Path': 'N/A (On-Demand Fetch)', 'Item Name': item.get('name'), 'Item ID': item_id, 
                'Mime Type': item.get('mimeType'), 'Current Download Restriction': str(is_restricted).upper(), 
                'Role': "No Permissions Found", 'Principal Type': "N/A", 'Email Address': "N/A", 'Owner': owner,
                'Google Drive URL': item.get('webViewLink'), 'Root Folder ID': item.get('parents', [])[0] if item.get('parents') else 'N/A'
            })
        else:
            for p in permissions:
                report_data.append({
                    'Full Path': 'N/A (On-Demand Fetch)', 'Item Name': item.get('name'), 'Item ID': item_id, 
                    'Mime Type': item.get('mimeType'), 'Current Download Restriction': str(is_restricted).upper(),
                    'Role': ROLE_MAP.get(p.get('role'), str(p.get('role')).capitalize()),
                    'Principal Type': ROLE_MAP.get(p.get('type'), str(p.get('type')).capitalize()),
                    'Email Address': p.get('emailAddress') or p.get('domain') or 'anyoneWithLink',
                    'Owner': owner, 'Google Drive URL': item.get('webViewLink'),
                    'Root Folder ID': item.get('parents', [])[0] if item.get('parents') else 'N/A'
                })

    logging.info(f"Finished processing data for {total_items} items.")
    return report_data, error_count

def generate_permission_report(drive_service, folder_id, user_email=None, progress_callback=None):
    """
    Generates a detailed permission report for all items under a folder (full scan).
    """
    logging.info(f"Starting full report generation for folder ID: {folder_id}")
    all_items = list_files_recursively(drive_service, folder_id)
    if not all_items:
        return [], 0 # Return empty list and zero errors if no items found

    item_ids = [item['id'] for item in all_items]
    
    report_data, error_count = get_report_for_items(drive_service, item_ids, progress_callback)
    
    path_map = {item['id']: item['path'] for item in all_items}
    for row in report_data:
        row['Full Path'] = path_map.get(row['Item ID'], 'N/A')

    if user_email:
        logging.info(f"Filtering full report for user: {user_email}")
        report_data = [row for row in report_data if row.get('Email Address', '').lower() == user_email.lower()]
            
    return report_data, error_count

def generate_domain_filtered_report(drive_service, folder_id, domain, progress_callback=None):
    """
    Generates a report containing only items accessible to at least one user from the specified domain.
    """
    logging.info(f"Starting domain-filtered report for folder ID: {folder_id}, domain: {domain}")
    
    full_report_data, initial_error_count = generate_permission_report(drive_service, folder_id, progress_callback=progress_callback)

    if not full_report_data:
        return [], initial_error_count

    item_ids_with_domain_access = set()
    for row in full_report_data:
        email = row.get('Email Address', '')
        if isinstance(email, str) and email.lower().endswith(f"@{domain.lower()}"):
            item_ids_with_domain_access.add(row['Item ID'])
    
    logging.info(f"Found {len(item_ids_with_domain_access)} items with permissions for domain '{domain}'.")

    if not item_ids_with_domain_access:
        return [], initial_error_count

    filtered_report = [row for row in full_report_data if row['Item ID'] in item_ids_with_domain_access]

    return filtered_report, initial_error_count

