import sys
from gui import App

def main():
    """
    Main entry point for the application.
    This function creates and runs the main GUI window.
    """
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        # This is a fallback for critical errors during startup.
        # Most errors will be handled and logged within the app itself.
        print(f"A fatal error occurred: {e}")
        # In a real distribution, you might write this to a crash log file.
        sys.exit(1)

if __name__ == '__main__':
    main()

