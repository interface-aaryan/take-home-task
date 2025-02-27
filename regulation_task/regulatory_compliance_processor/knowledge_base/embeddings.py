# knowledge_base/embeddings.py
import logging
import time
import os
import pickle
import hashlib
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

from ..config import EMBEDDING_MODEL, openai_client, EMBEDDING_DIMENSION

# Use centralized OpenAI client from config
client = openai_client

logger = logging.getLogger(__name__)
if client:
    logger.info("EmbeddingGenerator using OpenAI client from config")
    # Test if client is a dummy client or a real one
    try:
        client_type = client.__class__.__name__
        logger.info(f"OpenAI client type in EmbeddingGenerator: {client_type}")
    except Exception as e:
        logger.error(f"Error checking client type: {str(e)}")
else:
    logger.error("OpenAI client not initialized in config, embedding generation will fail")

class EmbeddingCache:
    """Cache for embeddings to avoid redundant API calls"""
    
    def __init__(self, cache_dir: Optional[str] = None):
        # Set up cache directory
        self.cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "cache",
            "embeddings"
        )
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # In-memory cache for faster access
        self.memory_cache = {}
        self.max_memory_cache = 10000  # Maximum entries to store in memory
        
        # Load cache stats if they exist
        self.stats_file = os.path.join(self.cache_dir, "cache_stats.pkl")
        self.stats = self._load_stats()
        
        logger.info(f"Embedding cache initialized at {self.cache_dir}")
        logger.info(f"Cache stats: {self.stats['hits']} hits, {self.stats['misses']} misses")
    
    def _load_stats(self) -> Dict[str, int]:
        """Load cache statistics from disk"""
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.warning(f"Error loading embedding cache stats: {str(e)}")
        
        # Default stats
        return {"hits": 0, "misses": 0, "saved_api_calls": 0}
    
    def _save_stats(self) -> None:
        """Save cache statistics to disk"""
        try:
            with open(self.stats_file, 'wb') as f:
                pickle.dump(self.stats, f)
        except Exception as e:
            logger.warning(f"Error saving embedding cache stats: {str(e)}")
    
    def _text_to_key(self, text: str) -> str:
        """Convert text to a cache key"""
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    def get(self, text: str) -> Optional[List[float]]:
        """Get embedding from cache if it exists"""
        key = self._text_to_key(text)
        
        # Check memory cache first
        if key in self.memory_cache:
            self.stats["hits"] += 1
            if self.stats["hits"] % 100 == 0:
                self._save_stats()
            return self.memory_cache[key]
        
        # Check disk cache
        cache_file = os.path.join(self.cache_dir, f"{key}.pkl")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'rb') as f:
                    embedding = pickle.load(f)
                
                # Add to memory cache
                if len(self.memory_cache) < self.max_memory_cache:
                    self.memory_cache[key] = embedding
                
                self.stats["hits"] += 1
                if self.stats["hits"] % 100 == 0:
                    self._save_stats()
                
                return embedding
            except Exception as e:
                logger.warning(f"Error reading embedding from cache: {str(e)}")
        
        self.stats["misses"] += 1
        return None
    
    def put(self, text: str, embedding: List[float]) -> None:
        """Add embedding to cache"""
        key = self._text_to_key(text)
        
        # Add to memory cache
        if len(self.memory_cache) < self.max_memory_cache:
            self.memory_cache[key] = embedding
        
        # Add to disk cache
        cache_file = os.path.join(self.cache_dir, f"{key}.pkl")
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(embedding, f)
        except Exception as e:
            logger.warning(f"Error writing embedding to cache: {str(e)}")
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        return self.stats.copy()

class EmbeddingGenerator:
    """Generate embeddings for text using OpenAI API with optimizations"""
    
    def __init__(self, model=EMBEDDING_MODEL):
        self.model = model
        self.embedding_dimension = EMBEDDING_DIMENSION  # From config
        
        # Initialize cache
        self.cache = EmbeddingCache()
        
        # Track requests for rate limiting
        self.last_request_time = 0
        self.min_request_interval = 0.1  # Seconds between requests
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3
        
        # Text normalization for better caching
        self.normalize_text = True
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text to improve cache hits"""
        if not self.normalize_text:
            return text
            
        # Basic normalization
        text = text.strip()
        text = " ".join(text.split())  # Normalize whitespace
        
        # Truncate very long texts to first 8000 chars for embedding
        if len(text) > 8000:
            text = text[:8000]
            
        return text
    
    def _get_embeddings_from_api(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings directly from API"""
        # Rate limiting
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        
        try:
            response = client.embeddings.create(
                model=self.model,
                input=texts,
                encoding_format="float"
            )
            
            # Update last request time
            self.last_request_time = time.time()
            
            # Reset error counter
            self.consecutive_errors = 0
            
            # Extract embeddings
            return [item.embedding for item in response.data]
            
        except Exception as e:
            # Increment error counter
            self.consecutive_errors += 1
            
            # Log error
            logger.error(f"Error generating embeddings from API: {str(e)}")
            
            # If we've had too many consecutive errors, raise an exception
            if self.consecutive_errors >= self.max_consecutive_errors:
                raise Exception(f"Too many consecutive embedding API errors: {self.consecutive_errors}")
                
            # Return empty embeddings in case of error
            return [np.zeros(self.embedding_dimension).tolist() for _ in texts]
    
    def _process_batch_with_cache(self, texts: List[str]) -> List[List[float]]:
        """Process a batch of texts, using cache where possible"""
        normalized_texts = [self._normalize_text(text) for text in texts]
        
        # Check cache for each text
        results = []
        uncached_indices = []
        uncached_texts = []
        
        for i, text in enumerate(normalized_texts):
            cached_embedding = self.cache.get(text)
            if cached_embedding is not None:
                results.append((i, cached_embedding))
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)
        
        # Get embeddings for uncached texts
        if uncached_texts:
            uncached_embeddings = self._get_embeddings_from_api(uncached_texts)
            
            # Update cache with new embeddings
            for i, embedding in enumerate(uncached_embeddings):
                text = uncached_texts[i]
                self.cache.put(text, embedding)
                
                # Update cache stats
                self.cache.stats["saved_api_calls"] += 1
                
                # Add to results
                results.append((uncached_indices[i], embedding))
                
            # Save cache stats
            if len(uncached_texts) > 0:
                self.cache.stats["saved_api_calls"] += len(uncached_texts)
                self.cache._save_stats()
        
        # Sort results by original index
        results.sort(key=lambda x: x[0])
        
        # Return embeddings in original order
        return [embedding for _, embedding in results]
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts with caching and optimizations
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        # Process in batches
        batch_size = 100  # Max batch size for API
        results = []
        
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = self._process_batch_with_cache(batch_texts)
            results.extend(batch_embeddings)
            
            # Avoid rate limits between batches
            if i + batch_size < len(texts):
                time.sleep(0.5)
        
        return results
    
    def get_embedding_dimension(self) -> int:
        """Get the dimension of the embeddings"""
        return self.embedding_dimension
    
    def calculate_similarity(self, embedding1: List[float], embedding2: List[float]) -> float:
        """
        Calculate cosine similarity between two embeddings
        
        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector
            
        Returns:
            Cosine similarity (0-1 range)
        """
        if not embedding1 or not embedding2:
            return 0.0
            
        # Convert to numpy arrays
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)
        
        # Calculate cosine similarity
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
            
        return dot_product / (norm1 * norm2)
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        return self.cache.get_stats()
    