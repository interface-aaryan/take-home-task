#!/usr/bin/env python
import sys
import os
import logging
import json
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Add the project root directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import required modules
from regulatory_compliance_processor.knowledge_base.langchain_vector_store import LangChainVectorStore
from regulatory_compliance_processor.knowledge_base.vector_store import VectorStore
from regulatory_compliance_processor.document_processing.parsers import DocumentParserFactory
from regulatory_compliance_processor.document_processing.extractors.rule_extractor import RuleBasedClauseExtractor

def test_langchain_vector_store():
    """Test the LangChain vector store implementation by building a small knowledge base"""
    
    # Create an instance of the LangChain vector store
    logger.info("Creating LangChain vector store")
    langchain_store = LangChainVectorStore()
    
    # For comparison, also create the standard FAISS vector store
    logger.info("Creating standard FAISS vector store")
    faiss_store = VectorStore()
    
    # Initialize the document parser and extractor
    parser_factory = DocumentParserFactory()
    extractor = RuleBasedClauseExtractor()
    
    # Find sample regulation files to process
    sample_reg_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 
        "regulatory_compliance_processor/data/regulatory_docs"
    )
    
    # If there are no files in the sample dir, use the main regulation directory
    if not os.path.exists(sample_reg_dir) or not os.listdir(sample_reg_dir):
        sample_reg_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            "data/regulations"
        )
    
    # Find a PDF file to use
    reg_files = []
    for file in os.listdir(sample_reg_dir):
        if file.lower().endswith('.pdf'):
            reg_files.append(os.path.join(sample_reg_dir, file))
    
    if not reg_files:
        logger.error("No regulation PDF files found for testing")
        return False
    
    # Use only one file for faster testing
    test_file = reg_files[0]
    logger.info(f"Testing with regulation file: {os.path.basename(test_file)}")
    
    try:
        # Parse the document
        logger.info(f"Parsing document")
        doc_content = parser_factory.parse_document(test_file)
        
        # Extract clauses using rule-based extractor
        logger.info(f"Extracting clauses from document")
        clauses = extractor.extract_clauses(doc_content)
        
        logger.info(f"Extracted {len(clauses)} clauses from document")
        
        # Add clauses to LangChain vector store
        logger.info(f"Adding clauses to LangChain vector store")
        langchain_store.add_clauses(clauses)
        
        # Add clauses to FAISS vector store
        logger.info(f"Adding clauses to FAISS vector store")
        faiss_store.add_clauses(clauses)
        
        # Get stats from both vector stores
        langchain_stats = langchain_store.get_stats()
        faiss_stats = faiss_store.get_stats()
        
        logger.info(f"LangChain vector store stats: {langchain_stats}")
        logger.info(f"FAISS vector store stats: {faiss_stats}")
        
        # Test search functionality
        test_query = "safety requirements"
        
        logger.info(f"Testing search with query: '{test_query}'")
        
        # Search in LangChain vector store
        logger.info(f"Searching LangChain vector store")
        langchain_results = langchain_store.search(test_query, k=3)
        
        # Search in FAISS vector store
        logger.info(f"Searching FAISS vector store")
        faiss_results = faiss_store.search(test_query, k=3)
        
        # Compare top results
        logger.info(f"LangChain found {len(langchain_results)} results")
        logger.info(f"FAISS found {len(faiss_results)} results")
        
        if langchain_results:
            logger.info(f"Top LangChain result: {langchain_results[0].get('title', 'No title')} (similarity: {langchain_results[0].get('similarity'):.4f})")
        
        if faiss_results:
            logger.info(f"Top FAISS result: {faiss_results[0].get('title', 'No title')} (similarity: {faiss_results[0].get('similarity'):.4f})")
        
        return True
        
    except Exception as e:
        logger.error(f"Error testing vector stores: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("Starting LangChain vector store test")
    success = test_langchain_vector_store()
    if success:
        logger.info("LangChain vector store test completed successfully")
    else:
        logger.error("LangChain vector store test failed")
        sys.exit(1)