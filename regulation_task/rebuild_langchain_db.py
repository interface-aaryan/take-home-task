#!/usr/bin/env python3
"""
Script to rebuild LangChain vector database from regulation PDFs
without disturbing the FAISS database or processing checkpoints.
"""

import os
import sys
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("rebuild_langchain.log")
    ]
)
logger = logging.getLogger("rebuild_langchain")

# Add the parent directory to sys.path to allow importing from the module
parent_dir = Path(__file__).parent
sys.path.append(str(parent_dir))

# Now import from the regulatory_compliance_processor module
from regulatory_compliance_processor.knowledge_base.langchain_vector_store import LangChainVectorStore
from regulatory_compliance_processor.knowledge_base.vector_store import VectorStore
from regulatory_compliance_processor.document_processing.parsers.pdf_parser import PDFParser
from regulatory_compliance_processor.document_processing.extractors.hybrid_extractor import HybridExtractor
from regulatory_compliance_processor.config import (
    REGULATORY_DOCS_PATH, VECTOR_DB_PATH
)

def main():
    """Main function to rebuild the LangChain database"""
    logger.info("Starting LangChain database rebuild")
    start_time = time.time()
    
    # Check if processing checkpoint exists
    checkpoint_path = os.path.join(parent_dir, "regulatory_compliance_processor", "data", "processing_checkpoint.json")
    if not os.path.exists(checkpoint_path):
        logger.error(f"Checkpoint file not found at {checkpoint_path}")
        return False
    
    # Load the checkpoint to know which documents have been processed
    with open(checkpoint_path, 'r') as f:
        checkpoint = json.load(f)
    
    logger.info(f"Found {len(checkpoint)} documents in checkpoint file")
    
    # Back up current LangChain DB if it exists
    langchain_db_path = os.path.join(VECTOR_DB_PATH)
    if os.path.exists(langchain_db_path) and os.listdir(langchain_db_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{langchain_db_path}_backup_{timestamp}"
        logger.info(f"Backing up existing LangChain DB to {backup_path}")
        shutil.copytree(langchain_db_path, backup_path)
    
    # Create new LangChain DB
    # First clear the existing data but don't recreate the directory
    for item in os.listdir(langchain_db_path):
        item_path = os.path.join(langchain_db_path, item)
        if os.path.isfile(item_path):
            os.remove(item_path)
        elif os.path.isdir(item_path):
            shutil.rmtree(item_path)
    
    langchain_store = LangChainVectorStore(vector_db_path=langchain_db_path)
    
    # Initialize the FAISS vector store for reading the original processed data
    faiss_store = VectorStore(vector_db_path=langchain_db_path)
    
    # Now for each document in the checkpoint, read the original PDF and process it
    for doc_name, doc_info in tqdm(checkpoint.items(), desc="Processing documents"):
        if doc_info.get("status") != "completed":
            logger.warning(f"Skipping {doc_name} as its status is not 'completed'")
            continue
        
        # Get the source document path
        doc_path = os.path.join(REGULATORY_DOCS_PATH, doc_name)
        if not os.path.exists(doc_path):
            logger.warning(f"Document {doc_path} not found, skipping")
            continue
        
        logger.info(f"Processing {doc_name}")
        try:
            # Parse the PDF
            parser = PDFParser()
            parse_result = parser.extract_text(doc_path)
            text = parser.get_text_from_result(parse_result)
            
            # Extract clauses using the hybrid extractor
            extractor = HybridExtractor()
            clauses = extractor.extract_clauses(
                text=text,
                document_id=doc_info.get("document_id"),
                document_version=doc_info.get("version", 1),
                source_document=doc_name
            )
            
            # Add clauses to the LangChain vector store
            if clauses:
                logger.info(f"Adding {len(clauses)} clauses from {doc_name} to LangChain DB")
                langchain_store.add_clauses(clauses)
            else:
                logger.warning(f"No clauses extracted from {doc_name}")
            
        except Exception as e:
            logger.error(f"Error processing {doc_name}: {str(e)}")
            continue
    
    elapsed_time = time.time() - start_time
    logger.info(f"Completed LangChain DB rebuild in {elapsed_time:.2f} seconds")
    
    # Print stats
    stats = langchain_store.get_stats()
    logger.info(f"LangChain DB stats: {stats}")
    
    return True

if __name__ == "__main__":
    success = main()
    if success:
        print("✅ LangChain database successfully rebuilt!")
    else:
        print("❌ Failed to rebuild LangChain database. Check the logs for details.")