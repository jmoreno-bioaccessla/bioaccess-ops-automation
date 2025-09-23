import logging
import os
from datetime import datetime
from pathlib import Path
import pandas as pd
import time

from src.auth import authenticate_and_get_service
from src.report_generator import generate_permission_report, get_report_for_items, generate_domain_filtered_report
from src.spreadsheet_handler import write_report_to_excel, save_audit_log
from src.permission_manager import process_changes, plan_changes, generate_rollback_actions
from src.spreadsheet_handler import write_report_to_csv

def _setup_project_directories():
    """Ensures that all necessary output directories exist."""
    Path("./reports").mkdir(exist_ok=True)
    Path("./archives").mkdir(exist_ok=True)
    Path("./logs").mkdir(exist_ok=True)

def _sanitize_filename(name):
    name = str(name)
    sanitized_name = name.replace(' ', '_').replace('/', '_').replace('\\', '_')
    return "".join(c for c in sanitized_name if c.isalnum() or c in ('_', '-')).strip() or "unnamed_item"

def _get_item_name(service, item_id):
    try:
        response = service.files().get(fileId=item_id, fields='name').execute()
        return response.get('name', 'UnknownItem')
    except Exception as e:
        logging.error(f"Could not retrieve name for item ID {item_id}: {e}")
        return "UnknownItem"

def run_fetch(folder_id, user_email=None, sponsor_domain=None, progress_callback=None):
    _setup_project_directories()
    logging.info("--- Authenticating for Fetch ---")
    service, _ = authenticate_and_get_service()
    if not service:
        logging.critical("Authentication failed.")
        return None

    root_folder_name = _sanitize_filename(_get_item_name(service, folder_id))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    error_count = 0
    if sponsor_domain:
        logging.info(f"Sponsor domain filter applied: {sponsor_domain}")
        report_data, error_count = generate_domain_filtered_report(service, folder_id, sponsor_domain, progress_callback)
        sanitized_domain = _sanitize_filename(sponsor_domain)
        output_filename = f"permissions_editor_{root_folder_name}_filtered_by_{sanitized_domain}.xlsx"
    else:
        report_data, error_count = generate_permission_report(service, folder_id, user_email, progress_callback)
        output_filename = f"permissions_editor_{root_folder_name}.xlsx"

    if report_data is None:
        return None
        
    if write_report_to_csv(report_data, os.path.join('archives', f"{timestamp}_fetch_{root_folder_name}_baseline.csv")):
        logging.info("Successfully created baseline archive.")

    output_path = os.path.join('reports', output_filename)
    return report_data, output_path, sponsor_domain, error_count

def prepare_apply_changes(excel_path, progress_callback=None):
    t_start = time.time()
    logging.info("--- Preparing to Apply Changes (Context-Aware) ---")
    service, auth_user_email = authenticate_and_get_service()
    if not service:
        logging.critical("Authentication failed during preparation.")
        return None

    try:
        t_read_start = time.time()
        input_df = pd.read_excel(excel_path, dtype=str).fillna('')
        if 'Item ID' not in input_df.columns or input_df.empty:
            raise ValueError("Input file missing 'Item ID' column or is empty.")
        
        item_ids_in_scope = input_df['Item ID'].unique().tolist()
        root_id = str(input_df.iloc[0].get('Root Folder ID', 'N/A'))
        logging.info(f"PERF: Reading Excel file and defining scope of {len(item_ids_in_scope)} items took {time.time() - t_read_start:.2f} seconds.")

        if not item_ids_in_scope:
            logging.info("No items found in the input file.")
            return [], [], root_id, False

    except Exception as e:
        logging.error(f"Failed to read or validate Excel file {excel_path}: {e}")
        return None

    t_fetch_start = time.time()
    logging.info(f"Fetching live data for {len(item_ids_in_scope)} items in scope...")
    live_data, _ = get_report_for_items(service, item_ids_in_scope, progress_callback=progress_callback)
    live_data_df = pd.DataFrame(live_data)
    logging.info(f"PERF: Context-aware fetch took {time.time() - t_fetch_start:.2f} seconds.")

    t_plan_start = time.time()
    execution_plan, self_mod_flag = plan_changes(input_df, live_data_df, auth_user_email)
    logging.info(f"PERF: Planning changes took {time.time() - t_plan_start:.2f} seconds.")
    
    logging.info(f"PERF: Total preparation time: {time.time() - t_start:.2f} seconds.")
    return execution_plan, live_data, root_id, self_mod_flag

def execute_apply_changes(plan, live_report_data, root_id, is_live_run, progress_callback=None):
    logging.info("--- Executing Apply Changes ---")
    service, _ = authenticate_and_get_service()
    if not service:
        logging.critical("Authentication failed during execution.")
        return None

    root_folder_name = _sanitize_filename(_get_item_name(service, root_id))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if write_report_to_csv(live_report_data, os.path.join('archives', f"{timestamp}_apply_{root_folder_name}_pre_changes.csv")):
        logging.info("Successfully created pre-apply changes archive.")

    audit_trail, success_count, error_count = process_changes(service, plan=plan, root_folder_id=root_id, dry_run=not is_live_run, progress_callback=progress_callback)
    
    if audit_trail:
        save_audit_log(audit_trail, os.path.join('logs', f"{timestamp}_apply_{root_folder_name}_audit.csv"))
    
    logging.info("--- Apply-Changes execution complete ---")
    return success_count, error_count

def prepare_rollback(log_file_path, root_id_override=None, progress_callback=None):
    t_start = time.time()
    logging.info("--- Preparing Rollback (Context-Aware) ---")
    service, auth_user_email = authenticate_and_get_service()
    if not service:
        logging.critical("Authentication failed during preparation.")
        return None

    try:
        t_read_start = time.time()
        log_file_abs = Path(log_file_path).resolve()
        audit_log_df = pd.read_csv(log_file_abs).fillna('')
        
        if audit_log_df.empty:
            logging.info("No actions found in the audit log to roll back.")
            return [], [], None, False
        
        item_ids_in_scope = audit_log_df[audit_log_df['Status'] == 'SUCCESS']['Item ID'].unique().tolist()
        root_id_from_log = audit_log_df.iloc[0]['Root Folder ID']
        logging.info(f"PERF: Reading audit log and defining scope of {len(item_ids_in_scope)} items took {time.time() - t_read_start:.2f} seconds.")
            
    except Exception as e:
        logging.error(f"Failed to read or process audit log '{log_file_path}': {e}")
        return None
    
    actual_root_id = root_id_override or root_id_from_log
    
    t_fetch_start = time.time()
    logging.info(f"Fetching live data for {len(item_ids_in_scope)} items in scope for rollback.")
    live_report_data, _ = get_report_for_items(service, item_ids_in_scope, progress_callback=progress_callback)
    logging.info(f"PERF: Context-aware fetch took {time.time() - t_fetch_start:.2f} seconds.")
    
    t_plan_start = time.time()
    rollback_plan, self_mod_flag = generate_rollback_actions(log_file_abs, live_report_data, auth_user_email)
    logging.info(f"PERF: Planning rollback took {time.time() - t_plan_start:.2f} seconds.")
    
    logging.info(f"PERF: Total preparation time: {time.time() - t_start:.2f} seconds.")
    return rollback_plan, live_report_data, actual_root_id, self_mod_flag

def execute_rollback(plan, live_report_data, root_id, is_live_run, progress_callback=None):
    logging.info("--- Executing Rollback ---")
    service, _ = authenticate_and_get_service()
    if not service:
        logging.critical("Authentication failed during execution.")
        return None

    root_folder_name = _sanitize_filename(_get_item_name(service, root_id))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if write_report_to_csv(live_report_data, os.path.join('archives', f"{timestamp}_rollback_{root_folder_name}_pre_rollback.csv")):
        logging.info("Successfully created pre-rollback archive.")
    
    audit_trail, success_count, error_count = process_changes(service, plan=plan, root_folder_id=root_id, dry_run=not is_live_run, progress_callback=progress_callback)
    
    if audit_trail:
        save_audit_log(audit_trail, os.path.join('logs', f"{timestamp}_rollback_{root_folder_name}_audit.csv"))
    
    logging.info("--- Rollback execution complete ---")
    return success_count, error_count

