#!/usr/bin/env python
# This file was merged with the main entry point in regulation_task/main.py
# This file is kept for compatibility but should not be modified directly.
# Please make changes to regulation_task/main.py instead.

import os
import sys
import logging

# Set up logging redirection
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("regulatory_compliance.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logger.warning("This module is deprecated. Please use regulation_task/main.py directly.")

# Import the main function from the outer main.py file
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from regulation_task.main import main

# Export the main function for backwards compatibility
if __name__ == "__main__":
    main()