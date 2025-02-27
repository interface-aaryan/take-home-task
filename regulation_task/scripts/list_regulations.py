#!/usr/bin/env python
"""Script to list all regulations in the knowledge base."""

import sys
import sqlite3
from pathlib import Path

# Add parent directory to path so we can import modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from regulatory_compliance_processor.config import DOCUMENT_DB_PATH

def main():
    """List all regulations in the database."""
    try:
        conn = sqlite3.connect(DOCUMENT_DB_PATH)
        cursor = conn.execute("SELECT id, file_name FROM documents")
        
        print("Regulations in the knowledge base:")
        print("==================================")
        
        rows = cursor.fetchall()
        if not rows:
            print("No regulations found in the database.")
        else:
            for row in rows:
                print(f"ID: {row[0]}, Filename: {row[1]}")
        
        conn.close()
        return 0
    except Exception as e:
        print(f"Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())