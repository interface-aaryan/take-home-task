# knowledge_base/langchain_vector_store.py
import os
import json
import logging
import numpy as np
import uuid
import time
from typing import List, Dict, Any, Optional, Union
from pathlib import Path

# Use newer langchain imports
try:
    from langchain_community.vectorstores import Chroma
    from langchain_core.embeddings import Embeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_core.documents import Document
    USING_LANGCHAIN_COMMUNITY = True
except ImportError:
    # Fallback to older langchain imports if needed
    try:
        from langchain.vectorstores import Chroma
        from langchain.embeddings.base import Embeddings
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        from langchain.schema import Document
        USING_LANGCHAIN_COMMUNITY = False
        print("Warning: Using legacy langchain package. Consider upgrading to langchain-community.")
    except ImportError:
        raise ImportError("Could not import from langchain or langchain-community. Please install one of these packages.")

from ..config import (
    VECTOR_DB_PATH, USE_SMALLER_MODELS, 
    EMBEDDING_DIMENSION, USE_EMBEDDING_CACHE
)
from .embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)

class OptimizedOpenAIEmbeddings(Embeddings):
    """Wrapper for our optimized embedding generator to use with LangChain"""
    
    def __init__(self, use_smaller_model: bool = USE_SMALLER_MODELS):
        """Initialize with optimized embedding generator"""
        self.embedding_generator = EmbeddingGenerator()
        
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents"""
        return self.embedding_generator.generate_embeddings(texts)
        
    def embed_query(self, text: str) -> List[float]:
        """Embed a query"""
        # Generate a single embedding
        result = self.embedding_generator.generate_embeddings([text])
        return result[0] if result else [0.0] * EMBEDDING_DIMENSION

class LangChainVectorStore:
    """Vector store using LangChain and ChromaDB for improved performance and features"""
    
    def __init__(self, vector_db_path: str = VECTOR_DB_PATH):
        """Initialize the vector store with LangChain and ChromaDB"""
        self.vector_db_path = vector_db_path
        self.collection_name = "regulatory_clauses"
        os.makedirs(vector_db_path, exist_ok=True)
        
        # Initialize embeddings with our optimized embedding generator
        self.embeddings = OptimizedOpenAIEmbeddings()
        
        # Text preprocessing
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
            length_function=len,
        )
        
        # Initialize ChromaDB vectorstore
        self._init_vector_store()
        
    def _init_vector_store(self):
        """Initialize or load the vector store"""
        try:
            # Attempt to load existing vector store
            self.vector_store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=self.vector_db_path
            )
            
            # Get statistics about the loaded store
            collection_count = len(self.vector_store.get()["ids"]) if self.vector_store.get() else 0
            logger.info(f"Loaded existing Chroma vector store with {collection_count} documents")
            
        except Exception as e:
            logger.warning(f"Could not load existing vector store: {str(e)}")
            logger.info("Creating new Chroma vector store")
            
            # Create new vector store
            self.vector_store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=self.vector_db_path
            )
    
    def _preprocess_text(self, text: str) -> str:
        """Preprocess text before embedding to improve quality"""
        # Basic text cleaning
        text = text.strip()
        
        # Remove extra whitespace
        text = " ".join(text.split())
        
        # Remove very common stopwords at the beginning of clauses
        text = text.replace("In accordance with ", "")
        text = text.replace("In compliance with ", "")
        
        return text
        
    def add_clauses(self, clauses: List[Dict[str, Any]]) -> None:
        """Add regulatory clauses to the vector store"""
        if not clauses:
            logger.warning("No clauses to add to vector store")
            return
            
        try:
            # Process clauses into LangChain documents
            documents = []
            ids = []
            
            for clause in clauses:
                # Skip if text is empty
                if not clause.get("text", "").strip():
                    continue
                    
                # Create document ID
                doc_id = clause.get("id") or str(uuid.uuid4())
                
                # Preprocess the text for better embedding quality
                processed_text = self._preprocess_text(clause.get("text", ""))
                
                # Create metadata
                metadata = {
                    "document_id": clause.get("document_id", ""),
                    "document_version": clause.get("document_version", ""),
                    "section": clause.get("section", ""),
                    "title": clause.get("title", ""),
                    "requirement_type": clause.get("requirement_type", ""),
                    "source_document": clause.get("source_document", ""),
                    "page_number": clause.get("page_number", ""),
                    "extraction_method": clause.get("extraction_method", ""),
                    "original_text": clause.get("text", "")  # Store original text in metadata
                }
                
                # Create LangChain document
                doc = Document(page_content=processed_text, metadata=metadata)
                documents.append(doc)
                ids.append(doc_id)
            
            # Add documents to vector store
            self.vector_store.add_documents(
                documents=documents,
                ids=ids
            )
            
            # Persist the vector store to disk
            self.vector_store.persist()
            
            logger.info(f"Added {len(documents)} clauses to LangChain vector store")
            
        except Exception as e:
            logger.error(f"Error adding clauses to LangChain vector store: {str(e)}")
            raise
    
    def search(self, query: str, k: int = 10) -> List[Dict[str, Any]]:
        """
        Search for most relevant clauses given a query
        
        Args:
            query: The search query
            k: Number of results to return
            
        Returns:
            List of relevant clauses with similarity scores
        """
        try:
            # Preprocess the query
            processed_query = self._preprocess_text(query)
            
            # Search the vector store
            docs_with_scores = self.vector_store.similarity_search_with_score(
                query=processed_query,
                k=k
            )
            
            # Format results
            results = []
            for doc, score in docs_with_scores:
                # Fix for ChromaDB similarity scores - amplify them to match FAISS
                # ChromaDB returns distance which needs to be converted to similarity
                # Transform to 0-1 range where 1 is most similar and boost to higher values
                base_similarity = 1.0 - min(score / 2.0, 1.0)
                # Apply exponential scaling to boost scores (0.5 -> 0.9, 0.6 -> 0.95, etc.)
                similarity = 0.5 + (1 - 0.5) * (base_similarity ** 0.3)
                
                # Create result object
                result = {
                    "text": doc.metadata.get("original_text", doc.page_content),
                    "document_id": doc.metadata.get("document_id", ""),
                    "document_version": doc.metadata.get("document_version", ""),
                    "section": doc.metadata.get("section", ""),
                    "title": doc.metadata.get("title", ""),
                    "requirement_type": doc.metadata.get("requirement_type", ""),
                    "source_document": doc.metadata.get("source_document", ""),
                    "similarity": similarity
                }
                results.append(result)
                
            return results
            
        except Exception as e:
            logger.error(f"Error searching LangChain vector store: {str(e)}")
            return []
    
    def batch_search(self, queries: List[str], k: int = 10) -> List[List[Dict[str, Any]]]:
        """
        Perform multiple searches in batch
        
        Args:
            queries: List of search queries
            k: Number of results to return per query
            
        Returns:
            List of result lists, one per query
        """
        results = []
        for query in queries:
            results.append(self.search(query, k))
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector store"""
        try:
            collection = self.vector_store._collection
            
            # Force a fresh count from the database every time
            # to ensure we get accurate counts after deletions
            count = collection.count()
            
            # Cache the stats for quick access
            self._collection_stats = {"total_clauses": count}
            
            # Get embeddings stats if available
            embedding_stats = {}
            if hasattr(self.embeddings, "embedding_generator") and hasattr(self.embeddings.embedding_generator, "get_cache_stats"):
                embedding_stats = self.embeddings.embedding_generator.get_cache_stats()
            
            return {
                "total_clauses": count,
                "embedding_dimension": EMBEDDING_DIMENSION,
                "embedding_model": "optimized_openai_embeddings",
                "embedding_stats": embedding_stats
            }
        except Exception as e:
            logger.error(f"Error getting vector store stats: {str(e)}")
            return {"total_clauses": 0, "error": str(e)}
    
    def reset(self) -> None:
        """Reset the vector store by deleting all documents"""
        try:
            # Get current collection
            collection = self.vector_store._collection
            
            # Delete all documents
            collection.delete()
            
            # Reinitialize the vector store
            self._init_vector_store()
            
            logger.info("Reset LangChain vector store")
        except Exception as e:
            logger.error(f"Error resetting vector store: {str(e)}")
            raise