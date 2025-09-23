import os
import sys
import logging
import httplib2 

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError
import google_auth_httplib2 # Import the authorization bridge

def _get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

SCOPES = ['https://www.googleapis.com/auth/drive']
CREDENTIALS_DIR_PATH = _get_resource_path('credentials')
TOKEN_FILE = os.path.join(CREDENTIALS_DIR_PATH, 'token.json')
CREDENTIALS_FILE = os.path.join(CREDENTIALS_DIR_PATH, 'credentials_DeskApp.json')

def authenticate_and_get_service():
    """ 
    Handles the OAuth 2.0 flow.
    Returns a tuple: (drive_service, authenticated_user_email) or (None, None) on failure.
    """
    os.makedirs(CREDENTIALS_DIR_PATH, exist_ok=True)
    
    if not os.path.exists(CREDENTIALS_FILE):
        logging.critical(f"FATAL: Client secrets file not found at '{CREDENTIALS_FILE}'. Please set it up."); return None, None

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            logging.warning(f"Corrupted token file at '{TOKEN_FILE}'. Deleting it."); os.remove(TOKEN_FILE)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logging.info("Refreshing expired access token...")
            try:
                creds.refresh(Request())
            except RefreshError:
                logging.warning(f"Failed to refresh token. Deleting invalid token."); os.remove(TOKEN_FILE); creds = None
            except Exception as e:
                logging.error(f"Unexpected error during token refresh: {e}"); creds = None
        
        if not creds:
            logging.info("No valid token found, starting new OAuth flow...")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0, timeout_seconds=120, prompt='select_account')
                with open(TOKEN_FILE, 'w') as token: token.write(creds.to_json())
                logging.info(f"Token saved to {TOKEN_FILE}")
            except Exception as e:
                logging.error(f"\n---Authentication flow failed or timed out. (Error: {e})---\n"); return None, None

    try:
        http_obj = httplib2.Http(cache=None)
        authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=http_obj)
        
        # Using static discovery by not specifying `cache_discovery=False`
        service = build('drive', 'v3', http=authed_http)
        
        about = service.about().get(fields='user').execute()
        user_email = about.get('user', {}).get('emailAddress')
        if not user_email:
            logging.error("Could not determine the authenticated user's email address.")
            return None, None
        logging.info(f"Authenticated successfully as: {user_email}")
        
        return service, user_email
    except Exception as e:
        logging.error(f"Failed to build Drive service or get user info: {e}"); return None, None

def reset_authentication():
    """
    Deletes the token.json file to force re-authentication on the next run.
    Returns True on success (or if file did not exist), False on failure.
    """
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
            logging.info(f"Authentication token deleted: {TOKEN_FILE}")
        else:
            logging.info("No authentication token to delete.")
        return True
    except Exception as e:
        logging.error(f"Failed to delete token file at {TOKEN_FILE}: {e}")
        return False

