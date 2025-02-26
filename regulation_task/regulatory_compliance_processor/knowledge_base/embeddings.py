# knowledge_base/embeddings.py
import openai
import logging
import time
from typing import List, Dict, Any
import numpy as np

from ..config import OPENAI_API_KEY, EMBEDDING_MODEL

# Configure OpenAI
openai.api_key = OPENAI_API_KEY

logger = logging.getLogger(__name__)
logger.info(f"OpenAI API key found: {'Yes' if openai.api_key else 'No'}")

class EmbeddingGenerator:
    """Generate embeddings for text using OpenAI API"""
    
    def __init__(self, model=EMBEDDING_MODEL):
        self.model = model
        self.embedding_dimension = 3072  # Default dimension for text-embedding-3-large
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        embeddings = []
        batch_size = 100  # OpenAI recommends batching
        
        # Process in batches to avoid rate limits and large requests
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            
            try:
                response = openai.embeddings.create(
                    model=self.model,
                    input=batch_texts,
                    encoding_format="float"
                )
                
                # Extract embeddings
                batch_embeddings = [item.embedding for item in response.data]
                embeddings.extend(batch_embeddings)
                
                # Avoid rate limits
                if i + batch_size < len(texts):
                    time.sleep(0.5)
                    
            except Exception as e:
                logger.error(f"Error generating embeddings for batch {i // batch_size + 1}: {str(e)}")
                # Return empty embeddings in case of error
                return [np.zeros(self.embedding_dimension).tolist() for _ in texts]
        
        return embeddings
    
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
    