try:
    print("Importing modules...")
    from regulatory_compliance_processor.web.app import app
    print("Import successful!")
except Exception as e:
    print(f"Import error: {str(e)}")
