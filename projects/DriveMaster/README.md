# DriveMaster Permissions Tool - User Guide

This guide provides instructions for using the DriveMaster Permissions Tool to manage Google Drive folder permissions in bulk using a simple Excel interface.

---

## 1. First-Time Setup & Authentication

The very first time you run the tool, you will need to authorize it to access your Google Drive account. This is a one-time process.

1.  **Run the Application:** Double-click the `DriveMasterTool.exe` file. The control panel will appear.
2.  **Trigger Authentication:** Click any of the "Run" buttons (e.g., "Run Fetch" after entering a Folder ID).
3.  **Browser Window:** A new tab will open in your web browser, prompting you to log in to your Google Account. **You must use your official organizational Google account.**
4.  **"Unverified App" Screen:** Google will likely show a "Google hasn't verified this app" warning. This is expected because this tool is for internal use.
    * Click **"Advanced"**.
    * Click **"Go to DriveMasterTool (unsafe)"**.
5.  **Grant Permission:** On the next screen, review the permissions and click **"Allow"**. This gives the tool the necessary access to manage your Drive files.
6.  **Confirmation:** You will see a message saying "The authentication flow has completed." You can now close the browser tab.

The tool will automatically create a `credentials/token.json` file. As long as this file exists, you will not have to log in again.

---

## 2. The Standard Workflow: Fetch, Edit, Apply

The most common way to use the tool is a three-step process.

### Step 2.1: Fetch Current Permissions

This step reads all the permissions from a Google Drive folder and creates an Excel file for you to edit.

1.  **Get the Folder ID:** In Google Drive, navigate to the folder you want to manage. The Folder ID is the long string of letters and numbers in the URL.
    * Example: `https://drive.google.com/drive/folders/`**`1Q_GFk5fC7huNF-F1eTLmNKvPPMA68nLw`**
2.  **Enter the ID:** Copy this ID and paste it into the **"Google Drive Folder ID"** box in the GUI.
3.  **Run Fetch:** Click the **"Run Fetch"** button. The Output Log will show the progress.
4.  **Open the Report:** When complete, a new `permissions_editor_...xlsx` file will be created in the `reports` folder. Open this file.

### Step 2.2: Edit the Excel File

The Excel file is your main interface for defining changes. You have two types of actions you can perform.

**A) Changing Permissions (`Action_Type` column)**

To change a user's permission, use the `Action_Type` dropdown on their specific row.

* **`MODIFY`**: To change a user's role. Select `MODIFY` in the `Action_Type` column and then select their desired new role (e.g., "Editor") in the **`New_Role`** column.
* **`REMOVE`**: To completely remove a user's access from that file. Simply select `REMOVE` in the `Action_Type` column.
* **`ADD`**: To grant a new user permission. Select `ADD` in the `Action_Type` column and fill out the three "ADD" columns:
    * **`New_Role`**: The role to grant (e.g., "Viewer").
    * **`Type of account (for ADD)`**: The type of principal (`user`, `group`, `domain`).
    * **`Email/Domain (for ADD)`**: The user/group email address or the domain name.

**B) Restricting Downloads (Using the `SET Download Restriction` column)**

This is a file-level setting that prevents Viewers and Commenters from downloading, printing, or copying a file.

* **Current Download Restriction:** This is a read-only column that shows you the file's current setting (`TRUE`, `FALSE`, or `N/A` for folders). Do not edit this column.
* **SET Download Restriction:** This is the action column. It is blank by default. To change the setting for a file, find any permission row for that file and use the dropdown to select `TRUE` or `FALSE`. You only need to set this on one row for the entire file.

### Step 2.3: Apply the Changes

After making all your desired changes in the Excel file, save and close it.

1.  **Select the File:** In the GUI's **"Apply Changes"** section, click **"Browse"** and select the `.xlsx` file you just edited.
2.  **Perform a Dry Run (Highly Recommended):** Leave the **"Make LIVE changes"** box **unchecked** and click **"Run Apply-Changes"**. Review the Output Log to ensure it matches your intent.
3.  **Perform a Live Run:** Once you are confident, check the **"Make LIVE changes"** box. Click **"Run Apply-Changes"** again and confirm "Yes" in the warning pop-up. The tool will now apply your changes to Google Drive.

An audit log of the operation will be saved in the `logs` folder for your records.

---

## 3. Undoing Changes with Rollback

If you need to revert the changes made during a specific "Apply Changes" run, you can use the `rollback` feature.

1.  **Select the Audit Log:** In the GUI's **"Rollback Changes"** section, click **"Browse"** and select the `..._apply_..._audit.csv` file from the `logs` folder that corresponds to the run you want to undo.
2.  **Run Rollback:** Check the **"Perform LIVE rollback"** box and click **"Run Rollback"**. Confirm "Yes" in the warning pop-up.
3.  The tool will automatically calculate and apply the inverse operations to restore the permissions to their previous state.

---

## 4. Understanding the Folders

The application will create several folders in the same directory where you run the `.exe`:

* **`reports/`**: Contains the user-facing `permissions_editor_...xlsx` files.
* **`archives/`**: Contains raw CSV backups of the permission states before any action is taken.
* **`logs/`**: Contains detailed CSV audit logs of every action performed.
* **`credentials/`**: Stores your `token.json` file after you log in.

---

## 5. Advanced - Switching User Accounts

If you need to run the tool with a different Google Account, you must first clear the current user's saved authentication token.

1.  Navigate to the `credentials` folder.
2.  Delete the `token.json` file.
3.  The next time you run an operation (e.g., "Run Fetch"), the tool will initiate the first-time setup and authentication process again (see Section 1), allowing you to log in with a new account.