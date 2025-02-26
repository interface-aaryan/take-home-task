import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = os.path.join(BASE_DIR, "data")
REGULATORY_DOCS_DIR = os.path.join(DATA_DIR, "regulatory_docs")
SOP_DIR = os.path.join(DATA_DIR, "sop")

# Create directories if they don't exist
os.makedirs(REGULATORY_DOCS_DIR, exist_ok=True)
os.makedirs(SOP_DIR, exist_ok=True)

# Knowledge base settings
VECTOR_DB_PATH = os.path.join(DATA_DIR, "vector_db")
DOCUMENT_DB_PATH = os.path.join(DATA_DIR, "document_db")

# OpenAI API settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    # Print warning if API key is not found
    print("WARNING: OpenAI API key not found in environment variables.")
    print("Using environment variable OPENAI_API_KEY only")
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")

# Initialize logging
import logging
config_logger = logging.getLogger(__name__)
config_logger.info("Configuring OpenAI client...")

# Initialize OpenAI client with version 1.64.0
try:
    # Import directly - should work with openai 1.64.0
    from openai import OpenAI
    
    # Set environment variable for API key if provided
    if OPENAI_API_KEY:
        os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    
    # Create client with no parameters to use env vars
    openai_client = OpenAI()
    
    # Log successful initialization
    config_logger.info(f"OpenAI client initialized. Client type: {openai_client.__class__.__name__}")
    config_logger.info(f"API key present: {'Yes' if OPENAI_API_KEY else 'No'}")
    
except Exception as e:
    config_logger.error(f"Error initializing OpenAI client: {str(e)}")
    
    # Create a dummy client as fallback
    class DummyClient:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                error_msg = "OpenAI client not properly initialized. Check your API key and environment."
                config_logger.error(error_msg)
                raise RuntimeError(error_msg)
            return method
    
    openai_client = DummyClient()

# Extraction settings
MIN_CLAUSE_LENGTH = 50
MAX_CLAUSE_LENGTH = 2000
CLAUSE_OVERLAP_THRESHOLD = 0.7

# Analysis settings
COMPLIANCE_THRESHOLD = 0.8
RELEVANCE_THRESHOLD = 0.75
MAX_RELEVANT_CLAUSES = 50