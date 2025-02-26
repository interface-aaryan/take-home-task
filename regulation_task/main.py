#!/usr/bin/env python
import sys
import os

# Add the project root directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the main function from the package
from regulatory_compliance_processor.main import main

if __name__ == "__main__":
    main()