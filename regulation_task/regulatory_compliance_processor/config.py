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
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")

# Extraction settings
MIN_CLAUSE_LENGTH = 50
MAX_CLAUSE_LENGTH = 2000
CLAUSE_OVERLAP_THRESHOLD = 0.7

# Analysis settings
COMPLIANCE_THRESHOLD = 0.8
RELEVANCE_THRESHOLD = 0.75
MAX_RELEVANT_CLAUSES = 50