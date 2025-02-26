import sys
import os

# Add the parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    print("Importing modules...")
    from regulation_task.regulatory_compliance_processor.web.app import app
    print("Import successful!")
except Exception as e:
    print(f"Import error: {str(e)}")
