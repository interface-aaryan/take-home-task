import sys
import os

# Add the project root to sys.path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

try:
    print("Importing modules...")
    from regulatory_compliance_processor.web.app import app
    print("Import successful!")
except Exception as e:
    print(f"Import error: {str(e)}")
