#!/usr/bin/env python
"""
Script to rebuild the vector store from the SQL database
"""

import os
import sys
import logging
from pathlib import Path

# Add parent directory to path so we can import modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from regulatory_compliance_processor.knowledge_base.document_store import DocumentStore
from regulatory_compliance_processor.knowledge_base.vector_store_factory import VectorStoreFactory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def rebuild_vector_store():
    """Rebuild the vector store from the document store"""
    try:
        logger.info("Starting vector store rebuild")
        
        # Initialize document store and vector store
        document_store = DocumentStore()
        vector_store = VectorStoreFactory.create_vector_store()
        
        # Get all regulatory clauses
        logger.info("Retrieving all regulatory clauses from database")
        all_clauses = document_store.get_all_regulatory_clauses()
        logger.info(f"Retrieved {len(all_clauses)} clauses from database")
        
        if not all_clauses:
            logger.warning("No clauses found in database. Vector store will be empty.")
            return False
            
        # Convert all IDs to strings for ChromaDB compatibility
        logger.info("Converting IDs to strings for ChromaDB compatibility")
        for clause in all_clauses:
            clause["id"] = str(clause["id"])
            clause["document_id"] = str(clause["document_id"])
        
        # Clear and rebuild vector store
        if hasattr(vector_store, 'vector_store') and hasattr(vector_store.vector_store, '_collection'):
            # For LangChain's ChromaDB
            logger.info("Detected LangChain ChromaDB vector store")
            
            # Get existing documents
            chroma_collection = vector_store.vector_store._collection
            try:
                all_document_ids = chroma_collection.get()["ids"]
                if all_document_ids:
                    logger.info(f"Deleting {len(all_document_ids)} existing documents from vector store")
                    chroma_collection.delete(ids=all_document_ids)
            except Exception as e:
                logger.warning(f"No existing documents found or error occurred: {str(e)}")
                
            # Add all clauses
            logger.info(f"Adding {len(all_clauses)} clauses to vector store")
            vector_store.add_clauses(all_clauses)
            
        elif hasattr(vector_store, 'reset'):
            # For vector stores with reset method
            logger.info("Using reset method for vector store")
            vector_store.reset()
            vector_store.add_clauses(all_clauses)
        else:
            # For other vector stores
            logger.info("Using rebuild_index for vector store")
            vector_store.rebuild_index(all_clauses)
            
        logger.info("Vector store rebuild completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error rebuilding vector store: {str(e)}")
        return False

if __name__ == "__main__":
    success = rebuild_vector_store()
    if success:
        print("Vector store rebuilt successfully")
        sys.exit(0)
    else:
        print("Failed to rebuild vector store")
        sys.exit(1)