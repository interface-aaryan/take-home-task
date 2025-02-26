# knowledge_base/vector_store.py
import os
import json
import logging
import numpy as np
import faiss
import pickle
from pathlib import Path
from typing import List, Dict, Any, Tuple

from .embeddings import EmbeddingGenerator
from ..config import VECTOR_DB_PATH

logger = logging.getLogger(__name__)

class VectorStore:
    """Vector store for semantic search of regulatory clauses"""
    
    def __init__(self, vector_db_path=VECTOR_DB_PATH):
        self.vector_db_path = vector_db_path
        self.index_path = os.path.join(vector_db_path, "faiss_index.bin")
        self.metadata_path = os.path.join(vector_db_path, "metadata.pkl")
        os.makedirs(vector_db_path, exist_ok=True)
        
        self.embedding_generator = EmbeddingGenerator()
        self.index = None
        self.metadata = []
        
        # Load existing index if available
        self._load_index()
    
    def _load_index(self):
        """Load FAISS index from disk if available"""
        try:
            if os.path.exists(self.index_path) and os.path.exists(self.metadata_path):
                self.index = faiss.read_index(self.index_path)
                
                with open(self.metadata_path, 'rb') as f:
                    self.metadata = pickle.load(f)
                
                logger.info(f"Loaded vector index with {len(self.metadata)} entries")
            else:
                # Initialize empty index
                embedding_dim = self.embedding_generator.get_embedding_dimension()
                self.index = faiss.IndexFlatL2(embedding_dim)
                self.metadata = []
                logger.info(f"Created new empty vector index with dimension {embedding_dim}")
                
        except Exception as e:
            logger.error(f"Error loading vector index: {str(e)}")
            # Initialize empty index as fallback
            embedding_dim = self.embedding_generator.get_embedding_dimension()
            self.index = faiss.IndexFlatL2(embedding_dim)
            self.metadata = []
    
    def _save_index(self):
        """Save FAISS index to disk"""
        try:
            faiss.write_index(self.index, self.index_path)
            
            with open(self.metadata_path, 'wb') as f:
                pickle.dump(self.metadata, f)
            
            logger.info(f"Saved vector index with {len(self.metadata)} entries")
            
        except Exception as e:
            logger.error(f"Error saving vector index: {str(e)}")
            raise
    
    def add_clauses(self, clauses: List[Dict[str, Any]]):
        """
        Add regulatory clauses to the vector store
        
        Args:
            clauses: List of clause objects with 'text' field
        """
        if not clauses:
            logger.warning("No clauses to add to vector store")
            return
        
        try:
            # Generate embeddings for all clauses
            texts = [clause["text"] for clause in clauses]
            embeddings = self.embedding_generator.generate_embeddings(texts)
            
            # Convert to numpy array
            embeddings_np = np.array(embeddings).astype('float32')
            
            # Add to FAISS index
            self.index.add(embeddings_np)
            
            # Add metadata
            for clause in clauses:
                self.metadata.append({
                    "id": clause.get("id"),
                    "document_id": clause.get("document_id"),
                    "document_version": clause.get("document_version"),
                    "clause_id": clause.get("clause_id"),
                    "section": clause.get("section"),
                    "title": clause.get("title"),
                    "text": clause.get("text"),
                    "requirement_type": clause.get("requirement_type"),
                    "source_document": clause.get("source_document")
                })
            
            # Save updated index
            self._save_index()
            
            logger.info(f"Added {len(clauses)} clauses to vector store")
            
        except Exception as e:
            logger.error(f"Error adding clauses to vector store: {str(e)}")
            raise
    
    def rebuild_index(self, all_clauses: List[Dict[str, Any]]):
        """
        Rebuild the entire index with the provided clauses
        
        Args:
            all_clauses: List of all clause objects to include in the index
        """
        try:
            # Initialize empty index
            embedding_dim = self.embedding_generator.get_embedding_dimension()
            self.index = faiss.IndexFlatL2(embedding_dim)
            self.metadata = []
            
            # Add all clauses
            self.add_clauses(all_clauses)
            
            logger.info(f"Rebuilt vector index with {len(all_clauses)} clauses")
            
        except Exception as e:
            logger.error(f"Error rebuilding vector index: {str(e)}")
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
        if not self.index or self.index.ntotal == 0:
            logger.warning("Vector store is empty, no results to return")
            return []
        
        try:
            # Generate query embedding
            query_embedding = self.embedding_generator.generate_embeddings([query])[0]
            query_embedding_np = np.array([query_embedding]).astype('float32')
            
            # Search in FAISS index
            k = min(k, self.index.ntotal)  # Can't return more results than we have
            distances, indices = self.index.search(query_embedding_np, k)
            
            # Prepare results
            results = []
            for i, idx in enumerate(indices[0]):
                if idx != -1:  # Valid index
                    # Convert distance to similarity score (1 - normalized distance)
                    # Convert numpy float32 to Python native float for JSON serialization
                    similarity = float(1.0 - min(distances[0][i] / 100.0, 1.0))
                    
                    result = self.metadata[idx].copy()
                    result["similarity"] = similarity
                    results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching vector store: {str(e)}")
            raise
    
    def batch_search(self, queries: List[str], k: int = 10) -> List[List[Dict[str, Any]]]:
        """
        Perform multiple searches in batch
        
        Args:
            queries: List of search queries
            k: Number of results to return per query
            
        Returns:
            List of result lists, one per query
        """
        if not self.index or self.index.ntotal == 0:
            logger.warning("Vector store is empty, no results to return")
            return [[] for _ in queries]
        
        try:
            # Generate query embeddings
            query_embeddings = self.embedding_generator.generate_embeddings(queries)
            query_embeddings_np = np.array(query_embeddings).astype('float32')
            
            # Search in FAISS index
            k = min(k, self.index.ntotal)  # Can't return more results than we have
            distances, indices = self.index.search(query_embeddings_np, k)
            
            # Prepare results
            all_results = []
            for q_idx in range(len(queries)):
                results = []
                for i, idx in enumerate(indices[q_idx]):
                    if idx != -1:  # Valid index
                        # Convert distance to similarity score (1 - normalized distance)
                        # Convert numpy float32 to Python native float for JSON serialization
                        similarity = float(1.0 - min(distances[q_idx][i] / 100.0, 1.0))
                        
                        result = self.metadata[idx].copy()
                        result["similarity"] = similarity
                        results.append(result)
                all_results.append(results)
            
            return all_results
            
        except Exception as e:
            logger.error(f"Error performing batch search: {str(e)}")
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector store"""
        return {
            "total_clauses": len(self.metadata),
            "dimension": self.index.d if self.index else 0,
            "index_type": type(self.index).__name__ if self.index else None
        }
    