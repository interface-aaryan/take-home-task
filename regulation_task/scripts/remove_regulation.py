#!/usr/bin/env python
"""
Script to remove a regulation from the knowledge base.
This will:
1. Create a new empty version of the regulation in the document_versions table
2. Remove regulatory clauses associated with the document from the database
3. Reset and rebuild the vector store without the removed regulation's clauses
This approach preserves document history while removing the regulation from active use.
"""

import os
import sys
import logging
import argparse
import gc
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Add parent directory to path so we can import modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from regulatory_compliance_processor.knowledge_base.document_store import DocumentStore
from regulatory_compliance_processor.knowledge_base.vector_store_factory import VectorStoreFactory
from regulatory_compliance_processor.config import EMBEDDING_BATCH_SIZE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def remove_regulation(regulation_filename: str, rebuild_vector_store: bool = True) -> bool:
    """
    Remove a regulation from the knowledge base while preserving document history
    
    Args:
        regulation_filename: The filename of the regulation to remove
        rebuild_vector_store: Whether to rebuild the vector store after removal
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Looking for regulation: {regulation_filename}")
        
        # Initialize document store
        document_store = DocumentStore()
        
        # Get all documents
        all_docs = document_store.get_all_documents()
        
        # Find the document to remove
        doc_to_remove = next((doc for doc in all_docs if doc["file_name"] == regulation_filename), None)
        
        if not doc_to_remove:
            logger.error(f"Regulation '{regulation_filename}' not found in the knowledge base")
            return False
        
        doc_id = doc_to_remove["id"]
        logger.info(f"Found regulation '{regulation_filename}' with ID {doc_id}")
        
        # Connect to SQLite DB and create a new empty version
        with document_store.conn:
            # First, get the latest version number
            cursor = document_store.conn.execute(
                "SELECT MAX(version) FROM document_versions WHERE document_id = ?", 
                (doc_id,)
            )
            latest_version = cursor.fetchone()[0] or 0
            
            # Create a new version with empty content
            new_version = latest_version + 1
            timestamp = datetime.now().isoformat()
            
            # Add new empty version to preserve history
            document_store.conn.execute(
                """
                INSERT INTO document_versions 
                (document_id, version, content, created_at, comment) 
                VALUES (?, ?, ?, ?, ?)
                """, 
                (doc_id, new_version, "", timestamp, "Removed via script - preserving history")
            )
            logger.info(f"Created new empty version {new_version} for document {doc_id}")
            
            # Delete clauses due to foreign key constraints
            cursor = document_store.conn.execute(
                "DELETE FROM regulatory_clauses WHERE document_id = ?", 
                (doc_id,)
            )
            clauses_deleted = cursor.rowcount
            logger.info(f"Deleted {clauses_deleted} regulatory clauses for document {doc_id}")
        
        # Rebuild vector store if requested
        if rebuild_vector_store:
            logger.info("Rebuilding vector store...")
            
            # Get vector store
            vector_store = VectorStoreFactory.create_vector_store()
            
            # Clear vector store
            if hasattr(vector_store, 'vector_store') and hasattr(vector_store.vector_store, '_collection'):
                # This is LangChain's ChromaDB implementation
                logger.info("Detected LangChain ChromaDB vector store")
                
                # Get all the documents currently in the vector store
                try:
                    logger.info("Getting all document IDs from vector store")
                    chroma_collection = vector_store.vector_store._collection
                    all_document_ids = chroma_collection.get()["ids"]
                    logger.info(f"Found {len(all_document_ids)} documents in vector store")
                    
                    # Delete all documents in the vector store
                    logger.info("Deleting all documents from vector store")
                    if all_document_ids:
                        chroma_collection.delete(ids=all_document_ids)
                    logger.info("Vector store cleared successfully")
                except Exception as e:
                    logger.error(f"Error clearing vector store: {str(e)}")
                    logger.info("Will attempt to rebuild with remaining documents anyway")
            else:
                # For other vector stores with reset method
                logger.info("Using reset method to clear vector store")
                try:
                    vector_store.reset()
                except Exception as e:
                    logger.error(f"Error resetting vector store: {str(e)}")
            
            # Get all remaining clauses from the document store
            remaining_clauses = document_store.get_all_regulatory_clauses()
            logger.info(f"Adding {len(remaining_clauses)} remaining clauses to vector store")
            
            # Add clauses to vector store in batches for better memory management
            batch_size = EMBEDDING_BATCH_SIZE
            
            for i in range(0, len(remaining_clauses), batch_size):
                batch_clauses = remaining_clauses[i:i+batch_size]
                
                # Convert all IDs to strings - fix for the ChromaDB issue
                for clause in batch_clauses:
                    clause["id"] = str(clause["id"])
                    clause["document_id"] = str(clause["document_id"])
                
                # Add batch to vector store
                if hasattr(vector_store, 'add_clauses'):
                    try:
                        vector_store.add_clauses(batch_clauses)
                        logger.info(f"Added batch {i//batch_size + 1}/{(len(remaining_clauses) + batch_size - 1)//batch_size} of clauses to vector store")
                    except Exception as e:
                        logger.error(f"Error adding clauses to vector store: {str(e)}")
                        # Continue with next batch
                        continue
                
                # Force memory cleanup between batches
                gc.collect()
                
            if hasattr(vector_store, 'rebuild_index') and not hasattr(vector_store, 'add_clauses'):
                vector_store.rebuild_index(remaining_clauses)
                
            logger.info("Vector store rebuilt successfully")
        
        logger.info(f"Successfully removed regulation '{regulation_filename}' from the knowledge base while preserving history")
        return True
    
    except Exception as e:
        logger.error(f"Error removing regulation: {str(e)}")
        return False

def main():
    """Main function to process command line arguments"""
    parser = argparse.ArgumentParser(description='Remove a regulation from the knowledge base')
    parser.add_argument('regulation', type=str, help='Filename of the regulation to remove')
    parser.add_argument('--no-rebuild', action='store_true', help='Skip rebuilding the vector store')
    parser.add_argument('--force-delete', action='store_true', help='Completely delete document including history (not recommended)')
    
    args = parser.parse_args()
    
    success = remove_regulation(args.regulation, not args.no_rebuild)
    
    if success:
        print(f"Successfully removed regulation '{args.regulation}' from the knowledge base")
        return 0
    else:
        print(f"Failed to remove regulation '{args.regulation}'")
        return 1

if __name__ == "__main__":
    sys.exit(main())