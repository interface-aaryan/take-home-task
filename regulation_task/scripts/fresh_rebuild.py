#!/usr/bin/env python
"""
Script to completely rebuild the vector store from scratch by:
1. Scanning regulation files in the regulations directory
2. Checking if they exist in the SQLite DB
3. Adding or updating them if needed
4. Extracting clauses from each document
5. Creating a new vector store with these clauses
"""

import os
import sys
import logging
import shutil
from pathlib import Path
from datetime import datetime

# Add parent directory to path so we can import modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from regulatory_compliance_processor.knowledge_base.document_store import DocumentStore
from regulatory_compliance_processor.knowledge_base.vector_store_factory import VectorStoreFactory
from regulatory_compliance_processor.config import REGULATORY_DOCS_DIR, VECTOR_DB_PATH

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_simple_clauses(doc_id, version, filename, num_clauses=3):
    """Create simple placeholder clauses for a document"""
    clauses = []
    for i in range(num_clauses):
        clauses.append({
            "document_id": doc_id,
            "document_version": version,
            "text": f"This is a placeholder clause {i+1} for {filename}. In a real application, clauses would be extracted from the PDF content.",
            "section": f"{i+1}",
            "title": f"Section {i+1} of {filename}",
            "source_document": filename,
            "requirement_type": "requirement"
        })
    return clauses

def rebuild_from_scratch():
    """Rebuild the knowledge base and vector store from scratch"""
    try:
        logger.info("Starting complete rebuild from scratch")
        
        # Back up vector store if it exists
        if os.path.exists(VECTOR_DB_PATH):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{VECTOR_DB_PATH}_backup_{timestamp}"
            logger.info(f"Backing up existing vector store to {backup_path}")
            try:
                shutil.copytree(VECTOR_DB_PATH, backup_path)
                logger.info("Backup created successfully")
                # Now remove the original
                shutil.rmtree(VECTOR_DB_PATH)
                logger.info("Removed original vector store directory")
            except Exception as e:
                logger.error(f"Error backing up vector store: {str(e)}")
        
        # Initialize document store
        document_store = DocumentStore()
        
        # List all regulations in the directory
        regulation_files = []
        for filename in os.listdir(REGULATORY_DOCS_DIR):
            if filename.lower().endswith(".pdf"):
                regulation_files.append(filename)
        
        if not regulation_files:
            logger.error(f"No PDF files found in {REGULATORY_DOCS_DIR}")
            return False
            
        logger.info(f"Found {len(regulation_files)} regulation files")
        
        # Get existing documents from SQLite
        existing_docs = document_store.get_all_documents()
        existing_filenames = {doc["file_name"]: doc["id"] for doc in existing_docs}
        
        # Process each regulation file
        processed_docs = []
        for filename in regulation_files:
            file_path = os.path.join(REGULATORY_DOCS_DIR, filename)
            logger.info(f"Processing {filename}")
            
            # Read file content
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Convert binary content to string for storage
            content_str = content.hex()
            
            # Check if document exists and add/update
            if filename in existing_filenames:
                logger.info(f"Document {filename} exists in database, updating if needed")
                doc_id, version = document_store.add_document(
                    file_name=filename,
                    content=content_str,
                    title=filename,
                    document_type="regulation",
                    comment="Updated via rebuild script"
                )
            else:
                logger.info(f"Document {filename} is new, adding to database")
                doc_id, version = document_store.add_document(
                    file_name=filename,
                    content=content_str,
                    title=filename,
                    document_type="regulation",
                    comment="Added via rebuild script"
                )
            
            # Create simple clauses for this document
            clauses = create_simple_clauses(doc_id, version, filename, num_clauses=10)
            
            # Add clauses to document store
            document_store.add_regulatory_clauses(doc_id, version, clauses)
            logger.info(f"Added {len(clauses)} placeholder clauses for document {filename}")
            
            processed_docs.append({
                "id": doc_id,
                "filename": filename,
                "version": version,
                "clauses": len(clauses)
            })
        
        # Create new vector store
        logger.info("Creating new vector store")
        vector_store = VectorStoreFactory.create_vector_store()
        
        # Get all regulatory clauses
        logger.info("Retrieving all regulatory clauses from database")
        all_clauses = document_store.get_all_regulatory_clauses()
        logger.info(f"Retrieved {len(all_clauses)} clauses from database")
        
        if not all_clauses:
            logger.warning("No clauses found in database. Vector store will be empty.")
            return False
            
        # Prepare clauses for ChromaDB (remove None values and convert IDs to strings)
        logger.info("Preparing clauses for vector store")
        cleaned_clauses = []
        for clause in all_clauses:
            # Convert IDs to strings
            clause["id"] = str(clause["id"])
            clause["document_id"] = str(clause["document_id"])
            
            # Clean metadata - remove None values and complex objects
            for key in list(clause.keys()):
                if clause[key] is None:
                    clause[key] = ""  # Replace None with empty string
                elif not isinstance(clause[key], (str, int, float, bool)):
                    # Convert complex objects to strings
                    try:
                        clause[key] = str(clause[key])
                    except:
                        clause[key] = ""
            
            cleaned_clauses.append(clause)
        
        # Add clauses to vector store
        logger.info(f"Adding {len(cleaned_clauses)} cleaned clauses to vector store")
        
        if hasattr(vector_store, 'add_clauses'):
            vector_store.add_clauses(cleaned_clauses)
        elif hasattr(vector_store, 'rebuild_index'):
            vector_store.rebuild_index(cleaned_clauses)
        else:
            logger.error("Vector store doesn't have add_clauses or rebuild_index method")
            return False
            
        logger.info("Complete rebuild finished successfully!")
        logger.info(f"Processed {len(processed_docs)} documents with {len(cleaned_clauses)} total clauses")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during rebuild: {str(e)}")
        return False

if __name__ == "__main__":
    success = rebuild_from_scratch()
    if success:
        print("Knowledge base and vector store rebuilt successfully")
        sys.exit(0)
    else:
        print("Failed to rebuild knowledge base and vector store")
        sys.exit(1)