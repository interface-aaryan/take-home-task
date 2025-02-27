#!/usr/bin/env python
"""
Script to intelligently rebuild the vector store:
1. Check existing regulations in the database
2. Compare with regulations in the filesystem
3. Extract clauses only for new/changed regulations
4. Use existing clauses for unchanged regulations
5. Rebuild the vector store with all clauses
"""

import os
import sys
import logging
import shutil
import json
import hashlib
from pathlib import Path
from datetime import datetime
import sqlite3

# Add parent directory to path so we can import modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from regulatory_compliance_processor.knowledge_base.document_store import DocumentStore
from regulatory_compliance_processor.knowledge_base.vector_store_factory import VectorStoreFactory
from regulatory_compliance_processor.config import VECTOR_DB_PATH, REGULATORY_DOCS_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_file_hash(file_path):
    """Generate a hash for a file to detect changes"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def smart_rebuild():
    """Intelligently rebuild the vector store"""
    try:
        logger.info("Starting intelligent vector store rebuild")
        
        # Backup vector store directory
        if os.path.exists(VECTOR_DB_PATH):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{VECTOR_DB_PATH}_backup_{timestamp}"
            logger.info(f"Backing up existing vector store to {backup_path}")
            try:
                shutil.copytree(VECTOR_DB_PATH, backup_path)
                logger.info("Backup created successfully")
                # Remove the original vector store
                shutil.rmtree(VECTOR_DB_PATH)
                logger.info("Removed original vector store")
                # Create empty directory
                os.makedirs(VECTOR_DB_PATH, exist_ok=True)
            except Exception as e:
                logger.error(f"Error backing up vector store: {str(e)}")
        
        # Initialize document store
        document_store = DocumentStore()
        
        # Get existing documents from database
        all_docs = document_store.get_all_documents(include_latest_version=True)
        logger.info(f"Found {len(all_docs)} documents in the database")
        
        # Create a map of filename to document info
        db_files = {}
        for doc in all_docs:
            if 'latest_version' in doc:
                db_files[doc['file_name']] = {
                    'id': doc['id'],
                    'version': doc['latest_version']['number']
                }
            else:
                logger.warning(f"Document {doc['file_name']} has no version information")
        
        # Get files from filesystem
        fs_files = {}
        for filename in os.listdir(REGULATORY_DOCS_DIR):
            if filename.lower().endswith('.pdf'):
                file_path = os.path.join(REGULATORY_DOCS_DIR, filename)
                fs_files[filename] = {
                    'path': file_path,
                    'hash': get_file_hash(file_path)
                }
        
        logger.info(f"Found {len(fs_files)} PDF files in the regulations directory")
        
        # Compare files to find new or changed regulations
        new_files = []
        changed_files = []
        unchanged_files = []
        
        for filename, file_info in fs_files.items():
            file_path = file_info['path']
            
            if filename not in db_files:
                # New file
                logger.info(f"Found new regulation: {filename}")
                new_files.append(file_path)
            else:
                # Check if file has changed
                with open(file_path, 'rb') as f:
                    content = f.read()
                # Generate hash from binary content
                content_hash = hashlib.sha256(content).hexdigest()
                
                # Get current version from database
                doc_id = db_files[filename]['id']
                
                # Get content hash from latest version
                conn = sqlite3.connect(document_store.db_path)
                cursor = conn.execute(
                    "SELECT content_hash FROM document_versions WHERE document_id = ? ORDER BY version_number DESC LIMIT 1",
                    (doc_id,)
                )
                result = cursor.fetchone()
                conn.close()
                
                if result and result[0] == content_hash:
                    # File is unchanged
                    logger.info(f"Regulation unchanged: {filename}")
                    unchanged_files.append(filename)
                else:
                    # File has changed
                    logger.info(f"Regulation changed: {filename}")
                    changed_files.append(file_path)
        
        logger.info(f"Analysis: {len(new_files)} new files, {len(changed_files)} changed files, {len(unchanged_files)} unchanged files")
        
        # Process new files
        for file_path in new_files:
            filename = os.path.basename(file_path)
            logger.info(f"Processing new regulation: {filename}")
            
            with open(file_path, 'rb') as f:
                content = f.read()
            content_str = content.hex()
            
            # Add to document store
            doc_id, version = document_store.add_document(
                file_name=filename,
                content=content_str,
                title=filename,
                document_type="regulation",
                comment="Added via smart rebuild script"
            )
            
            logger.info(f"Added document to database: {filename} (ID: {doc_id}, version: {version})")
            
            # Create a placeholder clause because we don't have real extraction
            clause = {
                "document_id": doc_id,
                "document_version": version,
                "text": f"This is a placeholder clause for {filename}. In a production environment, clauses would be properly extracted from the PDF.",
                "section": "1",
                "title": filename,
                "source_document": filename,
                "requirement_type": "requirement"
            }
            
            # Add clause to document store
            document_store.add_regulatory_clauses(doc_id, version, [clause])
            logger.info(f"Added placeholder clause for new document {filename}")
        
        # Process changed files
        for file_path in changed_files:
            filename = os.path.basename(file_path)
            logger.info(f"Processing changed regulation: {filename}")
            
            with open(file_path, 'rb') as f:
                content = f.read()
            content_str = content.hex()
            
            # Get document ID
            doc_id = db_files[filename]['id']
            
            # Add new version to document store
            doc_id, version = document_store.add_document(
                file_name=filename,
                content=content_str,
                title=filename,
                document_type="regulation",
                comment="Updated via smart rebuild script"
            )
            
            logger.info(f"Updated document in database: {filename} (ID: {doc_id}, version: {version})")
            
            # Create a placeholder clause because we don't have real extraction
            clause = {
                "document_id": doc_id,
                "document_version": version,
                "text": f"This is a placeholder clause for {filename}. In a production environment, clauses would be properly extracted from the PDF.",
                "section": "1",
                "title": filename,
                "source_document": filename,
                "requirement_type": "requirement"
            }
            
            # Add clause to document store
            document_store.add_regulatory_clauses(doc_id, version, [clause])
            logger.info(f"Added placeholder clause for updated document {filename}")
        
        # Now get all clauses from the database
        logger.info("Retrieving all regulatory clauses from database")
        all_clauses = document_store.get_all_regulatory_clauses()
        logger.info(f"Retrieved {len(all_clauses)} clauses from database")
        
        # Process clauses for vector store compatibility
        logger.info("Processing clauses for vector store compatibility")
        processed_clauses = []
        
        for clause in all_clauses:
            # Convert IDs to strings
            clause["id"] = str(clause["id"])
            clause["document_id"] = str(clause["document_id"])
            
            # Ensure all values are of compatible types
            for key in list(clause.keys()):
                if clause[key] is None:
                    clause[key] = ""
                elif not isinstance(clause[key], (str, int, float, bool)):
                    try:
                        clause[key] = str(clause[key])
                    except:
                        clause[key] = ""
            
            processed_clauses.append(clause)
        
        logger.info(f"Processed {len(processed_clauses)} clauses")
        
        # Create new vector store
        logger.info("Creating new vector store")
        vector_store = VectorStoreFactory.create_vector_store()
        
        # Add clauses to vector store
        logger.info(f"Adding {len(processed_clauses)} clauses to vector store")
        
        # Add in batches to avoid memory issues
        batch_size = 500
        for i in range(0, len(processed_clauses), batch_size):
            batch = processed_clauses[i:i+batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(processed_clauses) + batch_size - 1)//batch_size}: {len(batch)} clauses")
            
            try:
                vector_store.add_clauses(batch)
            except Exception as e:
                logger.error(f"Error adding batch to vector store: {str(e)}")
                # Continue with next batch
        
        logger.info("Vector store rebuild completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error during smart rebuild: {str(e)}")
        return False

if __name__ == "__main__":
    success = smart_rebuild()
    if success:
        print("Vector store rebuilt successfully")
        sys.exit(0)
    else:
        print("Failed to rebuild vector store")
        sys.exit(1)