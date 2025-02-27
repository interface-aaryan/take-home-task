import os
import multiprocessing
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = os.path.join(BASE_DIR, "data")
REGULATORY_DOCS_DIR = os.path.join(DATA_DIR, "regulatory_docs")
SOP_DIR = os.path.join(DATA_DIR, "sop")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

# Create directories if they don't exist
os.makedirs(REGULATORY_DOCS_DIR, exist_ok=True)
os.makedirs(SOP_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# Knowledge base settings
VECTOR_DB_PATH = os.path.join(DATA_DIR, "vector_db")
DOCUMENT_DB_PATH = os.path.join(DATA_DIR, "document_db")

# Multi-processing settings
MAX_WORKERS = min(multiprocessing.cpu_count(), 4)  # Limit to 4 workers max
PROCESSING_TIMEOUT = 600  # 10 minutes timeout for processing tasks

# OpenAI API settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    # Print warning if API key is not found
    print("WARNING: OpenAI API key not found in environment variables.")
    print("Using environment variable OPENAI_API_KEY only")

# Model settings
USE_SMALLER_MODELS = os.getenv("USE_SMALLER_MODELS", "false").lower() == "true"
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-3.5-turbo" if USE_SMALLER_MODELS else "gpt-4o")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002" if USE_SMALLER_MODELS else "text-embedding-3-large")
EMBEDDING_DIMENSION = 1536 if EMBEDDING_MODEL == "text-embedding-ada-002" else 3072  # Dimension varies by model

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
    config_logger.info(f"Using GPT model: {GPT_MODEL}")
    config_logger.info(f"Using embedding model: {EMBEDDING_MODEL} (dim: {EMBEDDING_DIMENSION})")
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
RELEVANCE_THRESHOLD = 0.6  # Lowered from 0.75 to capture more matches
MAX_RELEVANT_CLAUSES = 50

# Feature flags for optimizations
USE_RULE_BASED_EXTRACTION = True     # Use rule-based extraction
USE_HYBRID_EXTRACTION = True         # Use hybrid extraction (rule-based + LLM)
USE_EMBEDDING_CACHE = True           # Cache embeddings to reduce API calls
COMPRESS_LARGE_TEXTS = True          # Compress large texts to save memory
USE_PARALLEL_PROCESSING = True       # Process documents in parallel
USE_LANGCHAIN = True                 # Use LangChain with ChromaDB instead of FAISS
USE_TEXT_PREPROCESSING = True        # Use text preprocessing to improve embeddings

# Add a function to get the optimal batch size based on system memory
def get_optimal_batch_size():
    """Get optimal batch size based on system memory"""
    try:
        import psutil
        # Get available memory in GB
        available_memory = psutil.virtual_memory().available / (1024 ** 3)
        
        # Adjust batch size based on available memory
        if available_memory > 8:  # More than 8GB available
            return 100
        elif available_memory > 4:  # 4-8GB available
            return 50
        elif available_memory > 2:  # 2-4GB available
            return 20
        else:  # Less than 2GB available
            return 10
    except:
        # Default if psutil not available
        return 20

# Batch sizes for different operations
EMBEDDING_BATCH_SIZE = get_optimal_batch_size()
PROCESSING_BATCH_SIZE = max(1, get_optimal_batch_size() // 5)  # Smaller batch for processing