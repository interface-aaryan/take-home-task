import os
import sqlite3
from pathlib import Path

# Assume this is similar to your config
DATA_DIR = Path("data")
DOCUMENT_DB_PATH = os.path.join(DATA_DIR, "document_db")

# Try to connect to the database
try:
    conn = sqlite3.connect(DOCUMENT_DB_PATH)
    print(f"Successfully connected to {DOCUMENT_DB_PATH}")
    conn.close()
    print("Connection closed successfully")
except Exception as e:
    print(f"Error connecting to database: {str(e)}")
    
    # If the database file exists but is corrupted, rename it
    if os.path.exists(DOCUMENT_DB_PATH):
        backup_path = DOCUMENT_DB_PATH + ".bak"
        print(f"Backing up potentially corrupted database to {backup_path}")
        os.rename(DOCUMENT_DB_PATH, backup_path)
        print("Backup complete")
