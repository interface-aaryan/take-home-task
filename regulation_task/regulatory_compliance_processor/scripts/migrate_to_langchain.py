#!/usr/bin/env python3
"""
Script to migrate data from FAISS to LangChain DB without processing PDFs again.
This is a faster approach that directly copies data from FAISS to LangChain.
"""

import os
import sys
import json
import logging
import shutil
import uuid
from pathlib import Path
from datetime import datetime
import time

# Configure logging
log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "migrate_to_langchain.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file)
    ]
)
logger = logging.getLogger("migrate_to_langchain")

# Add the project root to sys.path to allow importing from the module
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

# Now import from the regulatory_compliance_processor module
from regulatory_compliance_processor.knowledge_base.langchain_vector_store import LangChainVectorStore
from regulatory_compliance_processor.knowledge_base.vector_store import VectorStore
from regulatory_compliance_processor.config import VECTOR_DB_PATH

def filter_metadata(metadata):
    """Filter out None values from metadata"""
    filtered = {}
    for key, value in metadata.items():
        # Skip None values and convert any complex types to strings
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            filtered[key] = value
        else:
            filtered[key] = str(value)
    return filtered

def prepare_clause(clause, index):
    """Prepare a clause for LangChain by filtering metadata and ensuring ID"""
    # Create a copy to avoid modifying the original
    new_clause = {}
    
    # Copy the text
    new_clause["text"] = clause.get("text", "")
    if not new_clause["text"]:
        new_clause["text"] = "Empty clause"
    
    # Generate a unique ID
    new_clause["id"] = f"clause_{index}_{uuid.uuid4().hex[:8]}"
    
    # Filter metadata to avoid None values
    for key, value in clause.items():
        if key == "text" or key == "id":
            continue
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            new_clause[key] = value
        else:
            # Convert complex types to strings
            new_clause[key] = str(value)
    
    return new_clause

def main():
    """Main function to migrate data from FAISS to LangChain"""
    logger.info("Starting migration from FAISS to LangChain")
    start_time = time.time()
    
    # Back up current LangChain DB if it exists
    langchain_db_path = os.path.join(VECTOR_DB_PATH)
    if os.path.exists(langchain_db_path) and os.listdir(langchain_db_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{langchain_db_path}_backup_{timestamp}"
        logger.info(f"Backing up existing LangChain DB to {backup_path}")
        shutil.copytree(langchain_db_path, backup_path)
    
    # Clear the existing LangChain data without recreating the directory
    for item in os.listdir(langchain_db_path):
        item_path = os.path.join(langchain_db_path, item)
        # Skip the FAISS files - we don't want to delete them
        if item in ["faiss_index.bin", "metadata.pkl"]:
            continue
        if os.path.isfile(item_path):
            os.remove(item_path)
        elif os.path.isdir(item_path):
            shutil.rmtree(item_path)
    
    # Initialize the stores
    faiss_store = VectorStore(vector_db_path=langchain_db_path)
    langchain_store = LangChainVectorStore(vector_db_path=langchain_db_path)
    
    # Load metadata from FAISS
    logger.info(f"Loading metadata from FAISS store with {len(faiss_store.metadata)} entries")
    
    # Prepare batch size for processing
    batch_size = 100
    total_entries = len(faiss_store.metadata)
    total_batches = (total_entries + batch_size - 1) // batch_size
    
    # Process in batches to avoid memory issues
    total_processed = 0
    
    for batch_idx in range(total_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, total_entries)
        
        logger.info(f"Processing batch {batch_idx+1}/{total_batches} (entries {start_idx}-{end_idx})")
        
        # Extract metadata batch
        batch_metadata = faiss_store.metadata[start_idx:end_idx]
        
        # Clean and prepare the clauses
        prepared_clauses = []
        for i, clause in enumerate(batch_metadata):
            # Skip if text is missing
            if not clause.get("text"):
                continue
                
            # Prepare the clause with filtered metadata
            prepared_clause = prepare_clause(clause, start_idx + i)
            prepared_clauses.append(prepared_clause)
        
        try:
            # Add to LangChain
            if prepared_clauses:
                langchain_store.add_clauses(prepared_clauses)
                total_processed += len(prepared_clauses)
                logger.info(f"Successfully added batch {batch_idx+1} ({len(prepared_clauses)} clauses)")
            else:
                logger.warning(f"No valid clauses in batch {batch_idx+1}")
        except Exception as e:
            logger.error(f"Error processing batch {batch_idx+1}: {str(e)}")
            # Continue with next batch
    
    elapsed_time = time.time() - start_time
    logger.info(f"Completed migration in {elapsed_time:.2f} seconds")
    logger.info(f"Total processed: {total_processed} out of {total_entries}")
    
    # Print stats
    faiss_stats = faiss_store.get_stats()
    langchain_stats = langchain_store.get_stats()
    logger.info(f"FAISS stats: {faiss_stats}")
    logger.info(f"LangChain stats: {langchain_stats}")
    
    return True

if __name__ == "__main__":
    success = main()
    if success:
        print("✅ Migration from FAISS to LangChain DB successful!")
        print(f"Original documents: {len(VectorStore(vector_db_path=VECTOR_DB_PATH).metadata)}")
        print(f"Documents in LangChain: {LangChainVectorStore(vector_db_path=VECTOR_DB_PATH).get_stats()['total_clauses']}")
    else:
        print("❌ Migration failed. Check the logs for details.")