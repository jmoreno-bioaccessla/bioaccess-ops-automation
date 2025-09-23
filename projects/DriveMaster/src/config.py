# src/config.py 

# This dictionary maps the API role names to the user-friendly UI names.
ROLE_MAP = {
    'reader': 'Viewer',
    'commenter': 'Commenter',
    'writer': 'Editor',
    'fileOrganizer': 'File Organizer',
    'organizer': 'Organizer',
    'owner': 'Owner'
}

# This dictionary does the reverse, mapping UI names back to API names.
# We can generate it automatically from the first map to avoid errors.
REVERSE_ROLE_MAP = {v: k for k, v in ROLE_MAP.items()}