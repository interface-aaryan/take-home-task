#!/usr/bin/env python
import sys
import os
import gc
import argparse
import logging

# Configure logging for this main file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("regulatory_compliance.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Add the project root directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the main function from the package
from regulatory_compliance_processor.main import main
from regulatory_compliance_processor.config import REGULATORY_DOCS_DIR, SOP_DIR

if __name__ == "__main__":
    logger.info("Starting regulatory compliance processing with memory management")
    
    # Parse arguments directly here
    parser = argparse.ArgumentParser(description="Regulatory Compliance Document Processor")
    parser.add_argument("--sop", type=str, help="Path to SOP document", default=os.path.join(SOP_DIR, "original.docx"))
    parser.add_argument("--reg-docs", type=str, help="Path to directory containing regulatory documents", default=REGULATORY_DOCS_DIR)
    parser.add_argument("--output", type=str, help="Path to output report file", default="compliance_report.json")
    parser.add_argument("--rebuild-kb", action="store_true", help="Rebuild knowledge base from scratch")
    parser.add_argument("--build-only", action="store_true", help="Only build knowledge base, don't process SOP")
    args = parser.parse_args()
    
    try:
        # Cleanup memory before starting
        gc.collect()
        logger.info(f"Starting with clean memory state")
        
        # Call main function with arguments
        main()
        
    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")
        sys.exit(1)
    
    logger.info("Regulatory compliance processing completed successfully")