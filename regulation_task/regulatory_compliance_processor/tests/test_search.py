#!/usr/bin/env python
import sys
import os
import logging
import json
from typing import Dict, List, Any

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
from regulatory_compliance_processor.knowledge_base.vector_store_factory import VectorStoreFactory
from regulatory_compliance_processor.config import RELEVANCE_THRESHOLD

def search_for_regulations(query: str, k: int = 10, use_langchain: bool = True) -> List[Dict[str, Any]]:
    """
    Search for regulations related to a query using either FAISS or LangChain vector store
    """
    vector_store = VectorStoreFactory.create_vector_store(use_langchain=use_langchain)
    logger.info(f"Using {'LangChain' if use_langchain else 'FAISS'} vector store")
    
    # Get stats from the vector store
    stats = vector_store.get_stats()
    clause_count = stats.get("total_clauses", 0)
    logger.info(f"Vector store has {clause_count} clauses")
    
    # Search for relevant clauses
    logger.info(f"Searching for: '{query}'")
    results = vector_store.search(query, k=k)
    
    # Log and return the results
    logger.info(f"Found {len(results)} results, {len([r for r in results if r.get('similarity', 0) >= RELEVANCE_THRESHOLD])} above threshold ({RELEVANCE_THRESHOLD})")
    for i, result in enumerate(results[:5]):  # Show top 5 results
        similarity = result.get("similarity", 0)
        title = result.get("title", "No title")
        text = result.get("text", "")[:100] + "..." if len(result.get("text", "")) > 100 else result.get("text", "")
        source = result.get("source_document", "Unknown source")
        
        logger.info(f"Result {i+1}: {title} (similarity: {similarity:.4f}) - Source: {source}")
        logger.info(f"  Text: {text}")
    
    return results

def search_multi_queries(use_langchain: bool = True):
    """Test multiple queries to assess vector store search performance"""
    # Test queries relevant to the SOP
    test_queries = [
        "purge procedure",
        "pressure safety valve",
        "natural gas",
        "nitrogen purging",
        "valve safety",
        "pressure requirements",
        "maximum allowable pressure",
        "oxygen monitoring",
        "gas leak detection",
        "combustible gas",
        "safety procedures",
        "fire protection"
    ]
    
    all_clause_ids = set()
    query_results = {}
    
    for query in test_queries:
        results = search_for_regulations(query, k=5, use_langchain=use_langchain)
        query_results[query] = [
            {
                "id": r.get("id", ""),
                "document_id": r.get("document_id", ""),
                "similarity": r.get("similarity", 0),
                "title": r.get("title", "No title"),
                "text_snippet": r.get("text", "")[:100] + "..." if len(r.get("text", "")) > 100 else r.get("text", ""),
                "source": r.get("source_document", "Unknown source")
            } 
            for r in results if r.get("similarity", 0) >= RELEVANCE_THRESHOLD
        ]
        
        # Track unique clause IDs
        for result in results:
            if result.get("similarity", 0) >= RELEVANCE_THRESHOLD:
                clause_id = f"{result.get('document_id')}_{result.get('id')}"
                all_clause_ids.add(clause_id)
    
    # Log summary
    logger.info(f"Total unique relevant clauses found: {len(all_clause_ids)}")
    
    # Return the results as a dictionary
    return query_results

if __name__ == "__main__":
    # Test both vector stores
    logger.info("=== Testing LangChain Vector Store Search ===")
    langchain_results = search_multi_queries(use_langchain=True)
    
    logger.info("\n=== Testing FAISS Vector Store Search ===")
    faiss_results = search_multi_queries(use_langchain=False)
    
    # Compare results
    langchain_count = sum(len(results) for results in langchain_results.values())
    faiss_count = sum(len(results) for results in faiss_results.values())
    
    logger.info(f"\n=== Comparison Summary ===")
    logger.info(f"LangChain found {langchain_count} relevant results across all queries")
    logger.info(f"FAISS found {faiss_count} relevant results across all queries")
    
    # Save the results to a file
    output = {
        "langchain_results": langchain_results,
        "faiss_results": faiss_results,
        "summary": {
            "langchain_count": langchain_count,
            "faiss_count": faiss_count
        }
    }
    
    with open("search_test_results.json", "w") as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"Results saved to search_test_results.json")