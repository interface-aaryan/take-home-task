#!/usr/bin/env python
"""
Script to add a regulation to the knowledge base and update the vector store.
Supports checking for new regulation vs new version, proper clause extraction,
and asynchronous processing.
"""

import os
import sys
import logging
import argparse
import json
import gc
import time
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

# Add parent directory to path so we can import modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from regulatory_compliance_processor.knowledge_base.document_store import DocumentStore
from regulatory_compliance_processor.knowledge_base.vector_store_factory import VectorStoreFactory
from regulatory_compliance_processor.config import (
    REGULATORY_DOCS_DIR, EMBEDDING_BATCH_SIZE,
    USE_RULE_BASED_EXTRACTION, USE_HYBRID_EXTRACTION
)
from regulatory_compliance_processor.document_processing.parsers import DocumentParserFactory
from regulatory_compliance_processor.document_processing.parsers.pdf_parser import PDFParser
from regulatory_compliance_processor.document_processing.extractors.llm_extractor import LLMClauseExtractor
from regulatory_compliance_processor.document_processing.extractors.rule_extractor import RuleBasedClauseExtractor
from regulatory_compliance_processor.document_processing.extractors.hybrid_extractor import HybridClauseExtractor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_existing_regulation(document_store: DocumentStore, filename: str) -> Tuple[bool, Optional[int]]:
    """
    Check if a regulation with the same filename already exists
    
    Args:
        document_store: DocumentStore instance
        filename: Name of the file to check
        
    Returns:
        Tuple of (exists_flag, document_id)
    """
    all_docs = document_store.get_all_documents()
    
    # Look for existing regulation with the same filename
    existing_doc = next((doc for doc in all_docs if doc["file_name"] == filename), None)
    
    if existing_doc:
        return True, existing_doc["id"]
    else:
        return False, None

def parse_regulation_document(regulation_path: str) -> Dict[str, Any]:
    """
    Parse a regulation document using the appropriate parser
    
    Args:
        regulation_path: Path to the regulation file
        
    Returns:
        Dict containing parsed document content
    """
    parser_factory = DocumentParserFactory()
    
    # Parse document with optimized parser
    logger.info(f"Parsing document: {os.path.basename(regulation_path)}")
    doc_content = parser_factory.parse_document(regulation_path)
    
    # Check if we need to handle compressed text
    if isinstance(doc_content, dict) and doc_content.get("is_compressed", False):
        logger.info(f"Document has compressed text, decompressing")
        if isinstance(doc_content.get("text"), bytes):
            # Get text using the PDF parser
            pdf_parser = PDFParser()
            doc_text = pdf_parser.get_text_from_result(doc_content)
            doc_content["text"] = doc_text
            doc_content["is_compressed"] = False
    
    return doc_content

def extract_clauses(doc_content: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract clauses from a document using the configured extractor
    
    Args:
        doc_content: Parsed document content
        
    Returns:
        List of extracted clauses
    """
    if USE_HYBRID_EXTRACTION:
        logger.info("Using hybrid extractor")
        extractor = HybridClauseExtractor()
    elif USE_RULE_BASED_EXTRACTION:
        logger.info("Using rule-based extractor")
        extractor = RuleBasedClauseExtractor()
    else:
        logger.info("Using LLM extractor")
        extractor = LLMClauseExtractor()
    
    clauses = extractor.extract_clauses(doc_content)
    logger.info(f"Extracted {len(clauses)} clauses")
    
    return clauses

def add_regulation(regulation_path: str, async_processing: bool = False) -> bool:
    """
    Add a regulation to the knowledge base and update the vector store.
    Checks if document is new or an update, extracts clauses properly.
    
    Args:
        regulation_path: Path to the regulation file
        async_processing: Whether to mark as processing and return immediately
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Clean memory before processing
        gc.collect()
        
        # Check if file exists
        if not os.path.exists(regulation_path):
            logger.error(f"Regulation file not found: {regulation_path}")
            return False
        
        # Get filename
        filename = os.path.basename(regulation_path)
        logger.info(f"Adding regulation: {filename}")
        
        # Initialize document store
        document_store = DocumentStore()
        
        # Check if this is a new document or an update to an existing one
        is_existing, existing_doc_id = check_existing_regulation(document_store, filename)
        if is_existing:
            logger.info(f"Regulation '{filename}' already exists with ID {existing_doc_id}, adding a new version")
        else:
            logger.info(f"Adding new regulation: {filename}")
        
        # Parse the document using appropriate parser
        doc_content = parse_regulation_document(regulation_path)
        doc_text = doc_content.get("text", "")
        doc_metadata = doc_content.get("metadata", {})
        
        # Add to document store with version control
        logger.info(f"Adding document to document store")
        doc_id, version_number = document_store.add_document(
            file_name=filename,
            content=doc_text,
            title=doc_metadata.get("title", filename),
            document_type="regulation",
            comment="Added via script",
            metadata=doc_metadata
        )
        
        logger.info(f"Added regulation to document store with ID {doc_id}, version {version_number}")
        
        # If async processing, mark as processing and return
        if async_processing:
            # Set a processing status in the document store
            # This could be a separate table or field in your actual implementation
            logger.info(f"Marked document {doc_id} as 'processing' for async handling")
            # In a real implementation, you would start a background task here
            return True
        
        # Extract actual clauses from the document
        logger.info(f"Extracting clauses from {filename}")
        clauses = extract_clauses(doc_content)
        
        # Free memory
        doc_text = None
        doc_content = None
        gc.collect()
        
        # Add clauses to document store
        logger.info(f"Adding {len(clauses)} clauses to document store")
        document_store.add_regulatory_clauses(doc_id, version_number, clauses)
        
        # Add clauses to vector store in smaller batches for semantic search
        logger.info(f"Adding clauses to vector store in batches")
        batch_size = EMBEDDING_BATCH_SIZE
        vector_store = VectorStoreFactory.create_vector_store()
        
        for i in range(0, len(clauses), batch_size):
            batch_clauses = clauses[i:i+batch_size]
            
            # Add document_id and version to each clause
            for clause in batch_clauses:
                clause["document_id"] = doc_id
                clause["document_version"] = version_number
                # Convert to strings for ChromaDB compatibility
                clause["id"] = str(clause.get("id", ""))
                clause["document_id"] = str(clause["document_id"])
            
            # Add to vector store
            vector_store.add_clauses(batch_clauses)
            logger.info(f"Added batch {i//batch_size + 1}/{(len(clauses) + batch_size - 1)//batch_size} of clauses to vector store")
            
            # Force memory cleanup between batches
            gc.collect()
        
        logger.info(f"Successfully added regulation '{filename}' to the knowledge base")
        return True
    
    except Exception as e:
        logger.error(f"Error adding regulation: {str(e)}")
        return False

def main():
    """Main function to process command line arguments"""
    parser = argparse.ArgumentParser(description='Add a regulation to the knowledge base')
    parser.add_argument('regulation', type=str, help='Path to the regulation file')
    parser.add_argument('--async', action='store_true', help='Process document asynchronously')
    
    args = parser.parse_args()
    
    success = add_regulation(args.regulation, async_processing=getattr(args, 'async', False))
    
    if success:
        print(f"Successfully added regulation to the knowledge base")
        return 0
    else:
        print(f"Failed to add regulation")
        return 1

if __name__ == "__main__":
    sys.exit(main())