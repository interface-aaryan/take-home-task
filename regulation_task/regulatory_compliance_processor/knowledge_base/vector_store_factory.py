# knowledge_base/vector_store_factory.py
import logging
from typing import Optional, Dict, Any

from ..config import VECTOR_DB_PATH, USE_LANGCHAIN
from .vector_store import VectorStore
from .langchain_vector_store import LangChainVectorStore

logger = logging.getLogger(__name__)

class VectorStoreFactory:
    """Factory for creating the appropriate vector store implementation"""
    
    @staticmethod
    def create_vector_store(use_langchain: Optional[bool] = None, vector_db_path: str = VECTOR_DB_PATH) -> Any:
        """
        Create a vector store based on configuration
        
        Args:
            use_langchain: Override config to use LangChain implementation
            vector_db_path: Path to store vector database
            
        Returns:
            VectorStore or LangChainVectorStore based on settings
        """
        # Determine which implementation to use
        if use_langchain is None:
            use_langchain = USE_LANGCHAIN
            
        if use_langchain:
            logger.info("Creating LangChain vector store implementation")
            return LangChainVectorStore(vector_db_path=vector_db_path)
        else:
            logger.info("Creating FAISS vector store implementation")
            return VectorStore(vector_db_path=vector_db_path)