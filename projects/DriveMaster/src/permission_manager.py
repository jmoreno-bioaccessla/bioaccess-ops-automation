import logging
import pandas as pd
from googleapiclient.errors import HttpError
from datetime import datetime
from src.config import REVERSE_ROLE_MAP

def _find_permission_id(drive_service, file_id, p_type, p_address, p_role_api):
    try:
        permissions = drive_service.permissions().list(fileId=file_id, fields='permissions(id,type,emailAddress,domain,role)').execute()
        for p in permissions.get('permissions', []):
            address_key = 'emailAddress' if p.get('type') in ['user', 'group'] else 'domain'
            permission_address = p.get(address_key, '')
            if (p.get('type') == p_type and permission_address.lower() == p_address.lower() and p.get('role') == p_role_api):
                return p.get('id')
    except HttpError as e:
        logging.error(f"Could not list permissions for file {file_id}: {e}")
    return None

def generate_rollback_actions(audit_log_path, live_report_data, auth_user_email):
    logging.info(f"Generating rollback actions from audit log: {audit_log_path}")
    self_modification_detected = False
    try:
        audit_log_df = pd.read_csv(audit_log_path).fillna('')
        successful_actions_df = audit_log_df[audit_log_df['Status'] == 'SUCCESS'].copy()
    except Exception as e:
        logging.error(f"Failed to read or parse audit log file {audit_log_path}: {e}"); return [], False
    
    if successful_actions_df.empty:
        logging.info("No successful actions found in the log to roll back."); return [], False

    item_name_map = {item['Item ID']: item['Item Name'] for item in live_report_data}
    root_folder_id = live_report_data[0]['Root Folder ID'] if live_report_data else ''

    actions_to_perform = []
    for _, log_entry in successful_actions_df.iterrows():
        item_id, cmd = str(log_entry['Item ID']), str(log_entry['Action_Command'])
        
        item_name = item_name_map.get(item_id, log_entry.get('Item Name', 'N/A'))
        full_path = log_entry.get('Full Path', 'N/A (Path not in log)')
        action = {'Item ID': item_id, 'Full Path': full_path, 'Item Name': item_name, 'Root Folder ID': root_folder_id}
        
        original_email = str(log_entry.get('Original_Email_Address', '')).lower()
        new_email = str(log_entry.get('New_Email_Address', '')).lower()
        if auth_user_email and (auth_user_email.lower() == original_email or auth_user_email.lower() == new_email):
            self_modification_detected = True

        if cmd == 'ADD':
            action.update({'Action_Type': 'REMOVE', 'Principal Type': log_entry['New_Principal_Type'], 'Email Address': log_entry['New_Email_Address'], 'Role': log_entry['New_Role']})
        elif cmd == 'REMOVE':
            action.update({'Action_Type': 'ADD', 'New_Role': log_entry['Original_Role'], 'Type of account (for ADD)': log_entry['Original_Principal_Type'], 'Email/Domain (for ADD)': log_entry['Original_Email_Address']})
        elif cmd == 'MODIFY':
            action.update({'Action_Type': 'MODIFY', 'Principal Type': log_entry['Original_Principal_Type'], 'Email Address': log_entry['Original_Email_Address'], 'Role': log_entry['New_Role'], 'New_Role': log_entry['Original_Role']})
        elif cmd == 'SET_DOWNLOAD_RESTRICTION':
            action.update({'Action_Type': 'SET_DOWNLOAD_RESTRICTION', 'Original_State': str(log_entry['New_Role']), 'Desired_State': str(log_entry['Original_Role'])})
        
        if action.get('Action_Type'):
            actions_to_perform.append(action)
            
    return actions_to_perform, self_modification_detected

def plan_changes(input_df, live_data_df, auth_user_email):
    logging.info("Planning potential changes by comparing the input file to live data...")
    action_plan = []
    self_modification_detected = False

    for item_id, item_group_df in input_df.groupby('Item ID'):
        file_info = item_group_df.iloc[0]

        restrictions = [str(val).strip().upper() for val in item_group_df['SET Download Restriction'].tolist() if str(val).strip()]
        desired_restr = restrictions[0] if restrictions else ''
        
        if desired_restr in ['TRUE', 'FALSE']:
            original_rows = live_data_df[live_data_df['Item ID'] == item_id]
            original_restr = "N/A"
            if not original_rows.empty:
                original_restr = str(original_rows.iloc[0]['Current Download Restriction']).upper()
            
            if desired_restr != original_restr:
                action = file_info.to_dict()
                action['Action_Type'] = 'SET_DOWNLOAD_RESTRICTION'
                action['Original_State'] = original_restr
                action['Desired_State'] = desired_restr
                action_plan.append(action)

        action_rows = item_group_df[item_group_df['Action_Type'].str.strip() != ''].copy()
        for _, row in action_rows.iterrows():
            action = row.to_dict()
            action_plan.append(action)
            
            cmd = str(row.get('Action_Type', '')).upper()
            if cmd in ['REMOVE', 'MODIFY']:
                email_to_check = str(row.get('Email Address', '')).lower()
                if auth_user_email and email_to_check == auth_user_email.lower():
                    self_modification_detected = True
            
    logging.info(f"Planning complete. Found {len(action_plan)} potential actions.")
    if self_modification_detected:
        logging.warning("SELF-MODIFICATION DETECTED: The planned changes will alter the current user's own permissions.")
        
    return action_plan, self_modification_detected

def process_changes(drive_service, plan, root_folder_id, dry_run=True, progress_callback=None):
    if not dry_run:
        logging.warning("--- Starting Live Mode: Changes WILL be applied to Google Drive. ---")
    else:
        logging.info("--- Starting Dry Run: No changes will be made. ---")

    audit_trail = []
    success_count = 0
    error_count = 0
    total_actions = len(plan)

    if not plan:
        logging.info("Execution plan is empty. No changes to process.")
        return audit_trail, success_count, error_count

    for i, action in enumerate(plan):
        if progress_callback:
            progress_callback(i + 1, total_actions)

        cmd = str(action.get('Action_Type')).strip().upper()
        item_id = str(action.get('Item ID'))
        
        entry = {'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'Root Folder ID': root_folder_id, 'Full Path': action.get('Full Path', ''), 'Item Name': action.get('Item Name', ''), 'Item ID': item_id, 'Action_Command': cmd, 'Status': 'DRY_RUN' if dry_run else 'PENDING', 'Details': '', 'Original_Principal_Type': str(action.get('Principal Type', '')), 'Original_Email_Address': str(action.get('Email Address', '')), 'Original_Role': str(action.get('Role', '')), 'New_Principal_Type': str(action.get('Type of account (for ADD)', '')), 'New_Email_Address': str(action.get('Email/Domain (for ADD)', '')), 'New_Role': str(action.get('New_Role', '')) }

        if dry_run:
            logging.info(f"[DRY RUN] Would perform '{cmd}' on Item ID: {item_id}")
            success_count += 1
            audit_trail.append(entry)
            continue
        
        try:
            if cmd == 'SET_DOWNLOAD_RESTRICTION':
                if action.get('Mime Type') == 'application/vnd.google-apps.folder':
                    details = "Skipped: Download restriction cannot be set on a folder."
                    logging.warning(f"[SKIPPED] Cannot set download restriction on folder '{action.get('Item Name')}'.")
                    entry.update({'Details': details, 'Status': 'SKIPPED'})
                else:
                    original_str = action.get('Original_State')
                    desired_str = action.get('Desired_State')
                    details = f"Set Restrict Download from '{original_str}' to '{desired_str}'"
                    drive_service.files().update(fileId=item_id, body={'copyRequiresWriterPermission': (desired_str == 'TRUE')}).execute()
                    entry.update({'Details': details, 'Original_Role': original_str, 'New_Role': desired_str, 'Status': 'SUCCESS'})
                    logging.info(f"[SUCCESS] {details} for Item ID: {item_id}")
                    success_count += 1

            elif cmd == 'ADD':
                p_type, p_address, p_role_ui = str(action.get('Type of account (for ADD)')).lower(), str(action.get('Email/Domain (for ADD)')), str(action.get('New_Role'))
                p_role_api = REVERSE_ROLE_MAP.get(p_role_ui.strip().title())
                if not all([p_type, p_address, p_role_api]): raise ValueError(f"Missing info for ADD on row linked to {item_id}.")
                drive_service.permissions().create(fileId=item_id, body={'type': p_type, 'role': p_role_api, 'emailAddress' if p_type in ['user', 'group'] else 'domain': p_address}, sendNotificationEmail=False).execute()
                entry['Details'] = f"Added {p_address} as {p_role_ui}."
                entry['Status'] = 'SUCCESS'
                logging.info(f"[SUCCESS] Performed {cmd} for '{p_address}' on Item ID: {item_id}")
                success_count += 1

            elif cmd == 'REMOVE':
                p_type, p_address, p_role_ui = str(action.get('Principal Type')).lower(), str(action.get('Email Address')), str(action.get('Role'))
                p_role_api = REVERSE_ROLE_MAP.get(p_role_ui.strip().title())
                if not all([p_type, p_address, p_role_api]): raise ValueError(f"Missing info for REMOVE on row linked to {item_id}.")
                pid = _find_permission_id(drive_service, item_id, p_type, p_address, p_role_api)
                if pid:
                    drive_service.permissions().delete(fileId=item_id, permissionId=pid).execute()
                    entry['Details'] = f"Removed {p_address} as {p_role_ui}."
                    entry['Status'] = 'SUCCESS'
                    logging.info(f"[SUCCESS] Performed {cmd} for '{p_address}' on Item ID: {item_id}")
                    success_count += 1
                else: raise ValueError(f"Permission not found for {p_address} with role {p_role_ui} to remove.")

            elif cmd == 'MODIFY':
                p_type, p_address, old_ui, new_ui = str(action.get('Principal Type')).lower(), str(action.get('Email Address')), str(action.get('Role')), str(action.get('New_Role'))
                old_api, new_api = REVERSE_ROLE_MAP.get(old_ui.strip().title()), REVERSE_ROLE_MAP.get(new_ui.strip().title())
                if not all([p_type, p_address, old_api, new_api]): raise ValueError(f"Missing/invalid role info for MODIFY on row linked to {item_id}.")
                pid = _find_permission_id(drive_service, item_id, p_type, p_address, old_api)
                if pid:
                    drive_service.permissions().update(fileId=item_id, permissionId=pid, body={'role': new_api}).execute()
                    entry['Details'] = f"Modified {p_address} from {old_ui} to {new_ui}."
                    entry['Status'] = 'SUCCESS'
                    logging.info(f"[SUCCESS] Performed {cmd} for '{p_address}' on Item ID: {item_id}")
                    success_count += 1
                else: raise ValueError(f"Permission not found for {p_address} with role {old_ui} to modify.")
        
        except (ValueError, HttpError) as e:
            entry['Status'] = 'ERROR' if isinstance(e, HttpError) else 'SKIPPED'
            entry['Details'] = str(e)
            logging.error(f"[{entry['Status']}] {cmd} on Item ID: {item_id}. Reason: {e}")
            error_count += 1
        
        audit_trail.append(entry)

    return audit_trail, success_count, error_count

