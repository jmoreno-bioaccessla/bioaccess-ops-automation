#drive_permissions_cook_v9_02May2025 
#!/usr/bin/env python3
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError

import httplib2
import logging
import time
import random
import csv
import argparse

# ---- CONFIG ----
httplib2.debuglevel = 4
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]
logging.basicConfig(
    filename='permissions.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def get_credentials():
    """
    Authenticate and return OAuth credentials (Drive & Sheets).
    """
    creds = None
    try:
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    except (FileNotFoundError, ValueError):
        logging.info("No valid token.json, starting OAuth flow.")
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logging.info("Refreshing token")
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080, access_type='offline', prompt='consent')
        with open('token.json', 'w', encoding='utf-8') as token:
            token.write(creds.to_json())
            logging.info("token.json saved")
    return creds


def get_email_to_name_title_mapping(sheets_service, sheet_id, range_name, max_retries=5):
    """
    Build a mapping email -> (name, title) from a sheet range.
    """
    retries = 0
    while retries < max_retries:
        try:
            resp = sheets_service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range=range_name
            ).execute()
            mapping = {}
            for row in resp.get('values', []):
                if len(row) >= 3 and row[1]:
                    email = row[1].strip().lower()
                    mapping[email] = (row[0].strip(), row[2].strip())
            return mapping
        except HttpError as e:
            if e.resp.status in [429,500,502,503,504]:
                wait = (2**retries) + random.random()
                logging.info(f"Retry mapping {retries+1} after {wait:.1f}s")
                time.sleep(wait)
                retries += 1
            else:
                logging.error(f"Mapping error: {e}")
                break
        except Exception as e:
            logging.error(f"Mapping exception: {e}")
            break
    return {}


def list_all_folders_and_files(service, parent_id, max_retries=5):
    """
    Recursively list all Drive items under a parent folder.
    """
    query = f"'{parent_id}' in parents"
    items = []
    page_token = None
    retries = 0
    while True:
        try:
            resp = service.files().list(
                q=query,
                fields='nextPageToken, files(id,name,mimeType,parents)',
                pageSize=1000,
                pageToken=page_token
            ).execute()
            for f in resp.get('files', []):
                items.append(f)
                if f['mimeType'] == 'application/vnd.google-apps.folder':
                    items.extend(list_all_folders_and_files(service, f['id']))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        except HttpError as e:
            if e.resp.status in [429,500,502,503,504] and retries < max_retries:
                wait = (2**retries) + random.random()
                logging.info(f"Retry listing {retries+1} after {wait:.1f}s")
                time.sleep(wait)
                retries += 1
            else:
                logging.error(f"Error listing: {e}")
                break
    return items


def build_item_hierarchy(all_items):
    """
    Attach subitems to each folder in-place and return root-level items.
    """
    for it in all_items:
        if it['mimeType'] == 'application/vnd.google-apps.folder':
            it['subitems'] = []
    item_map = {it['id']: it for it in all_items}
    roots = []
    for it in all_items:
        parents = it.get('parents', [])
        if parents and parents[0] in item_map:
            item_map[parents[0]]['subitems'].append(it)
        else:
            roots.append(it)
    return roots


def flatten_hierarchy(item, path=None):
    """
    Return list of full paths as lists of (id,name) tuples.
    """
    current = [] if path is None else list(path)
    current.append((item['id'], item['name']))
    rows = [current]
    for child in item.get('subitems', []):
        rows.extend(flatten_hierarchy(child, current))
    return rows


def fetch_permissions(service, file_id, max_retries=5):
    """
    Fetch permissions for a given file/folder.
    """
    retries = 0
    while True:
        try:
            resp = service.permissions().list(
                fileId=file_id,
                fields='permissions(emailAddress,role,type)'
            ).execute()
            return resp.get('permissions', [])
        except HttpError as e:
            if e.resp.status in [429,500,502,503,504] and retries < max_retries:
                wait = (2**retries) + random.random()
                logging.info(f"Retry perms {retries+1} for {file_id}")
                time.sleep(wait)
                retries += 1
            else:
                logging.error(f"Error perms for {file_id}: {e}")
                return []


def has_general_access(perms):
    """
    Return 'Yes' if shared broadly, else 'No'.
    """
    for p in perms:
        if p.get('type') in ['anyone','anyoneWithLink','domain','group']:
            return 'Yes'
    return 'No'


def main():
    parser = argparse.ArgumentParser(description='Drive permissions report')
    parser.add_argument('--root',   required=True, help='Root folder ID')
    parser.add_argument('--output', required=True, help='Output CSV filename')
    args = parser.parse_args()

    creds = get_credentials()
    drive_svc = build('drive', 'v3', credentials=creds)
    sheets_svc = build('sheets','v4', credentials=creds)
    logging.info("Drive & Sheets services initialized")

    # --- Load email->(name,title) mapping from sheets ---
    first_id         = '1P5uLqvEkN_G4ho7ty52eugz0nmOlGWFqgUwJorFievE'
    sponsors_range   = 'Sponsors!B:D'
    bioaccess_range  = 'bioaccess!B:D'
    second_id        = '1-1p-XQ-sMqpQ3aJUwlJRgfQhesNi8LZYQovE3-RzCHY'
    second_range     = "'Lista de contactos'!B19:D"

    sponsors_map = get_email_to_name_title_mapping(sheets_svc, first_id, sponsors_range)
    bio_map      = get_email_to_name_title_mapping(sheets_svc, first_id, bioaccess_range)
    second_map   = get_email_to_name_title_mapping(sheets_svc, second_id, second_range)
    email_to_name_title = {**sponsors_map, **bio_map, **second_map}

    # 1) List Drive items
    items = list_all_folders_and_files(drive_svc, args.root)
    logging.info(f"Fetched {len(items)} Drive items")

    # 2) Build & flatten hierarchy
    tree      = build_item_hierarchy(items)
    flattened = []
    for node in tree:
        flattened.extend(flatten_hierarchy(node))

    # 3) Fetch permissions and collect all emails
    perm_map   = {}
    all_emails = set()
    for it in items:
        perms = fetch_permissions(drive_svc, it['id'])
        perm_map[it['id']] = perms
        for p in perms:
            email = p.get('emailAddress')
            if email:
                all_emails.add(email.lower())
    sorted_emails = sorted(all_emails)

    # --- Prepare header rows ---
    names_header  = ['Full Path','Item ID'] + [ email_to_name_title.get(e,('Unknown',''))[0] for e in sorted_emails ] + ['']
    titles_header = ['',''] + [ email_to_name_title.get(e,('','Unknown'))[1] for e in sorted_emails ] + ['']
    emails_header = ['',''] + sorted_emails + ['']

    # 4) Build data rows
    rows = []
    for path in flattened:
        full_path = '/' + '/'.join([n for _,n in path])
        item_id   = path[-1][0]
        perms     = perm_map.get(item_id, [])
        row_perms = ['No Access'] * len(sorted_emails)
        for p in perms:
            email = p.get('emailAddress','').lower()
            role  = p.get('role','')
            if email in sorted_emails:
                row_perms[sorted_emails.index(email)] = role
        general = has_general_access(perms)
        rows.append([full_path, item_id] + row_perms + [general])

    # 5) Write CSV with three header rows
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(names_header)
        writer.writerow(titles_header)
        writer.writerow(emails_header)
        writer.writerows(rows)
    logging.info(f"CSV written: {args.output}")
    print(f"Report saved to {args.output}")

if __name__ == '__main__':
    main()
