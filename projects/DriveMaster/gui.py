import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import logging
from queue import Queue
import os
from PIL import Image, ImageTk

from src.controller import run_fetch, prepare_apply_changes, execute_apply_changes, prepare_rollback, execute_rollback
from src.auth import reset_authentication
from src.spreadsheet_handler import write_report_to_excel

class GuiHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))

class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("DriveMaster Control Panel")
        self.geometry("900x900")

        try:
            icon_path = os.path.join(os.path.dirname(__file__), 'assets', 'app_icon.ico')
            self.iconbitmap(icon_path)
        except Exception as e:
            logging.warning(f"Could not load application icon: {e}")

        header_frame = ttk.Frame(self, padding=(10, 10, 10, 0))
        header_frame.pack(fill="x")
        header_frame.columnconfigure(0, weight=1); header_frame.columnconfigure(2, weight=1)
        title_container = ttk.Frame(header_frame); title_container.grid(row=0, column=1)

        try:
            logo_path = os.path.join(os.path.dirname(__file__), 'assets', 'logo.png')
            img = Image.open(logo_path); img.thumbnail((150, 60))
            self.logo_image = ImageTk.PhotoImage(img)
            ttk.Label(title_container, image=self.logo_image).pack(side="left", padx=(0, 10))
        except FileNotFoundError:
            ttk.Label(title_container, text="[Logo]", font=('Helvetica', 12, 'italic')).pack(side="left", padx=(0, 10))
            
        ttk.Label(title_container, text='DriveMaster: Permissions Control Panel', font=('Helvetica', 16, 'bold')).pack(side="left")

        main_canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=main_canvas.yview)
        self.scrollable_frame = ttk.Frame(main_canvas, padding="10")

        self.scrollable_frame.bind("<Configure>", lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all")))
        self.canvas_window = main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        main_canvas.bind("<Configure>", lambda e: main_canvas.itemconfig(self.canvas_window, width=e.width))
        
        main_canvas.configure(yscrollcommand=scrollbar.set)
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.create_fetch_widgets()
        self.create_apply_widgets()
        self.create_rollback_widgets()
        self.create_advanced_widgets()
        self.create_progress_widgets()
        self.create_output_widgets()
        
        self.log_queue = Queue()
        self.queue_handler = GuiHandler(self.log_queue)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[self.queue_handler])
        
        self.after(100, self.poll_log_queue)

    def create_fetch_widgets(self):
        frame = ttk.LabelFrame(self.scrollable_frame, text="1. Fetch Permissions", padding="10")
        frame.pack(fill="x", pady=5)
        
        ttk.Label(frame, text="Google Drive Folder ID:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.fetch_id_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.fetch_id_var).grid(row=0, column=1, sticky="ew", padx=5)

        ttk.Label(frame, text="Optional User Email Filter:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.fetch_email_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.fetch_email_var).grid(row=1, column=1, sticky="ew", padx=5)

        ttk.Label(frame, text="Optional Sponsor Domain Filter:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.fetch_domain_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.fetch_domain_var).grid(row=2, column=1, sticky="ew", padx=5)

        self.fetch_button = ttk.Button(frame, text="Run Fetch", command=self.on_fetch)
        self.fetch_button.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        
        frame.columnconfigure(1, weight=1)

    def create_apply_widgets(self):
        frame = ttk.LabelFrame(self.scrollable_frame, text="2. Apply Changes", padding="10")
        frame.pack(fill="x", pady=5)
        self.apply_file_var = tk.StringVar()
        ttk.Label(frame, text="Permissions Excel File:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(frame, textvariable=self.apply_file_var, state="readonly").grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(frame, text="Browse...", command=lambda: self.apply_file_var.set(filedialog.askopenfilename(filetypes=[("Excel Files", "*.xlsx")]))).grid(row=0, column=2, padx=5)
        self.apply_live_var = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Make LIVE changes (default is a safe Dry Run)", variable=self.apply_live_var).grid(row=1, column=0, columnspan=3, sticky="w", padx=5)
        self.apply_button = ttk.Button(frame, text="Run Apply-Changes", command=self.on_apply)
        self.apply_button.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        frame.columnconfigure(1, weight=1)

    def create_rollback_widgets(self):
        frame = ttk.LabelFrame(self.scrollable_frame, text="3. Rollback Changes", padding="10")
        frame.pack(fill="x", pady=5)
        self.log_file_var = tk.StringVar()
        ttk.Label(frame, text="Audit Log File:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(frame, textvariable=self.log_file_var, state="readonly").grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(frame, text="Browse...", command=lambda: self.log_file_var.set(filedialog.askopenfilename(filetypes=[("Log Files", "*.csv")]))).grid(row=0, column=2, padx=5)
        self.rollback_live_var = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Perform LIVE rollback (default is a safe Dry Run)", variable=self.rollback_live_var).grid(row=1, column=0, columnspan=3, sticky="w", padx=5)
        self.rollback_button = ttk.Button(frame, text="Run Rollback", command=self.on_rollback)
        self.rollback_button.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        frame.columnconfigure(1, weight=1)

    def create_advanced_widgets(self):
        frame = ttk.LabelFrame(self.scrollable_frame, text="Advanced Settings", padding="10")
        frame.pack(fill="x", pady=5)
        ttk.Button(frame, text="Switch User Account", command=self.on_reset_auth).pack(side="left", padx=5, pady=5)
        ttk.Label(frame, text="Deletes the saved login token to allow a different Google user to sign in.").pack(side="left", padx=10, fill="x")

    def create_progress_widgets(self):
        self.progress_frame = ttk.LabelFrame(self.scrollable_frame, text="Progress", padding="10")
        self.progress_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", expand=True, pady=(0, 5))
        self.progress_label = ttk.Label(self.progress_frame, text="Idle", anchor="center")
        self.progress_label.pack(fill="x", expand=True)

    def create_output_widgets(self):
        self.progress_frame.pack(fill="x", pady=5)
        self.progress_frame.pack_forget() 
        frame = ttk.LabelFrame(self.scrollable_frame, text="Output Log", padding="10")
        frame.pack(fill="both", expand=True, pady=5)
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(button_frame, text="Clear Log", command=self.clear_output).pack(side="right")
        self.output_text = tk.Text(frame, wrap="word", height=10, font=("Courier New", 9))
        self.output_text.pack(fill="both", expand=True)

    def poll_log_queue(self):
        while not self.log_queue.empty():
            self.output_text.insert(tk.END, self.log_queue.get() + '\n')
            self.output_text.see(tk.END)
        self.after(100, self.poll_log_queue)

    def clear_output(self):
        self.output_text.delete(1.0, tk.END)

    def run_in_thread(self, target, *args):
        threading.Thread(target=target, args=args, daemon=True).start()

    def update_progress(self, current, total):
        if total > 0:
            percentage = (current / total) * 100
            self.progress_bar['maximum'] = 100
            self.progress_bar['value'] = percentage
            self.progress_label['text'] = f"{int(percentage)}% Complete ({current} of {total} items)"
        else:
            self.progress_label['text'] = "Operation in progress..."
            self.progress_bar['mode'] = 'indeterminate'
            self.progress_bar.start(10)

    def set_ui_state(self, is_busy):
        state = "disabled" if is_busy else "normal"
        self.fetch_button.config(state=state)
        self.apply_button.config(state=state)
        self.rollback_button.config(state=state)
        
    def show_progress(self, initial_message="Discovering items..."):
        self.progress_frame.pack(fill="x", pady=5, before=self.scrollable_frame.winfo_children()[-1])
        self.progress_label['text'] = initial_message
        self.update_progress(0, 0)
        self.set_ui_state(True)

    def hide_progress(self):
        self.set_ui_state(False)
        self.progress_frame.pack_forget()
        self.progress_bar.stop()
        self.progress_bar['mode'] = 'determinate'

    def on_fetch(self):
        self.clear_output()
        folder_id = self.fetch_id_var.get()
        if not folder_id: return messagebox.showerror("Error", "Please enter a Folder ID.")
        
        user_email = self.fetch_email_var.get() or None
        sponsor_domain = self.fetch_domain_var.get() or None
        
        self.show_progress()
        self.run_in_thread(self._fetch_worker, folder_id, user_email, sponsor_domain)

    def _fetch_worker(self, folder_id, user_email, sponsor_domain):
        result = run_fetch(folder_id, user_email, sponsor_domain, progress_callback=self.update_progress)
        self.after(0, self._on_fetch_complete, result)

    def _on_fetch_complete(self, result):
        self.hide_progress()
        if result is None: return 
        
        report_data, output_path, domain_filter, error_count = result
        
        if error_count > 0:
            messagebox.showwarning("Incomplete Report", 
                f"Fetch complete, but data for {error_count} item(s) could not be retrieved due to insufficient permissions. "
                "The generated report is incomplete.")

        if not report_data: return logging.info("--- Fetch complete (no data to write) ---")

        while True:
            try:
                if write_report_to_excel(report_data, output_path, domain_filter):
                    logging.info(f"User-facing Excel report saved to {output_path}")
                logging.info("--- Fetch complete ---")
                break 
            except PermissionError:
                if not messagebox.askyesno("File In Use", f"The report file is currently open:\n\n{output_path}\n\nPlease close it to proceed."):
                    logging.warning("Fetch cancelled by user.")
                    break
            except Exception as e:
                messagebox.showerror("Error", f"An unexpected error occurred: {e}")
                break

    def on_apply(self):
        excel_file = self.apply_file_var.get()
        if not excel_file: return messagebox.showerror("Error", "Please select a permissions Excel file.")

        self.clear_output()
        self.show_progress("Preparing to apply changes...")
        self.run_in_thread(self._apply_prepare_worker, excel_file)

    def _apply_prepare_worker(self, excel_file):
        result = prepare_apply_changes(excel_file, progress_callback=self.update_progress)
        self.after(0, self._on_apply_prepare_complete, result)

    def _on_apply_prepare_complete(self, result):
        if result is None:
            self.hide_progress()
            return

        plan, live_data, root_id, self_mod_flag = result
        num_affected = len({action['Item ID'] for action in plan})
        if num_affected == 0:
            self.hide_progress()
            return messagebox.showinfo("No Changes", "No changes were detected.")

        if self_mod_flag and not messagebox.askyesno("Confirm Self-Modification", "!!! WARNING !!!\nThis operation will modify your own permissions. Are you sure?"):
            self.hide_progress()
            return logging.warning("Operation cancelled by user.")

        is_live = self.apply_live_var.get()
        if messagebox.askyesno("Confirm Action", f"This will affect {num_affected} item(s).\nMode: {'LIVE' if is_live else 'Dry Run'}\nProceed?"):
            self.show_progress(initial_message="Executing changes...")
            self.run_in_thread(self._execute_apply_worker, plan, live_data, root_id, is_live)
        else:
            self.hide_progress()
            logging.warning("Operation cancelled by user.")

    def _execute_apply_worker(self, plan, live_data, root_id, is_live):
        execute_apply_changes(plan, live_data, root_id, is_live, progress_callback=self.update_progress)
        self.after(0, self.hide_progress)

    def on_rollback(self):
        log_file = self.log_file_var.get()
        if not log_file: return messagebox.showerror("Error", "Please select an audit log file.")

        self.clear_output()
        self.show_progress("Preparing rollback...")
        self.run_in_thread(self._rollback_prepare_worker, log_file)

    def _rollback_prepare_worker(self, log_file):
        result = prepare_rollback(log_file, progress_callback=self.update_progress)
        self.after(0, self._on_rollback_prepare_complete, result)

    def _on_rollback_prepare_complete(self, result):
        if result is None:
            self.hide_progress()
            return
        
        plan, live_data, root_id, self_mod_flag = result
        num_affected = len({action['Item ID'] for action in plan})
        if num_affected == 0:
            self.hide_progress()
            return messagebox.showinfo("No Changes", "No actions to roll back.")

        if self_mod_flag and not messagebox.askyesno("Confirm Self-Modification", "!!! WARNING !!!\nThis rollback will modify your own permissions. Are you sure?"):
            self.hide_progress()
            return logging.warning("Rollback cancelled by user.")

        is_live = self.rollback_live_var.get()
        if messagebox.askyesno("Confirm Rollback", f"This will affect {num_affected} item(s).\nMode: {'LIVE' if is_live else 'Dry Run'}\nProceed?"):
            self.show_progress(initial_message="Executing rollback...")
            self.run_in_thread(self._execute_rollback_worker, plan, live_data, root_id, is_live)
        else:
            self.hide_progress()
            logging.warning("Rollback cancelled by user.")
    
    def _execute_rollback_worker(self, plan, live_data, root_id, is_live):
        execute_rollback(plan, live_data, root_id, is_live, progress_callback=self.update_progress)
        self.after(0, self.hide_progress)

    def on_reset_auth(self):
        if messagebox.askyesno("Confirm Action", "This will log you out. Are you sure?"):
            if reset_authentication():
                messagebox.showinfo("Success", "Authentication has been reset.")
            else:
                messagebox.showerror("Error", "Could not delete the token file.")

if __name__ == "__main__":
    app = App()
    app.mainloop()

