# document_processing/extractors/llm_extractor.py
import logging
import json
import time
from typing import List, Dict, Any
import re
import os

from ...config import GPT_MODEL, openai_client

logger = logging.getLogger(__name__)

# Use the client from config
client = openai_client

if client:
    logger.info("LLMClauseExtractor using OpenAI client from config")
    # Test if client is a dummy client or a real one
    try:
        client_type = client.__class__.__name__
        logger.info(f"OpenAI client type: {client_type}")
    except:
        pass
else:
    logger.error("OpenAI client not initialized in config, extraction will fail")

class LLMClauseExtractor:
    """Extract regulatory clauses using LLM"""
    
    def __init__(self, model=GPT_MODEL):
        self.model = model
    
    def extract_clauses(self, document_content: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract regulatory clauses from document content using GPT
        
        Args:
            document_content: Dict containing document text and metadata
            
        Returns:
            List of extracted clauses with metadata
        """
        text = document_content.get("text", "")
        file_name = document_content.get("file_name", "")
        
        # Split text into smaller chunks to handle context length limitations
        # Smaller chunks = faster processing
        chunks = self._split_text_into_chunks(text, max_chunk_size=5000)
        
        all_clauses = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)} from {file_name}")
            
            try:
                # Extract clauses from this chunk
                chunk_clauses = self._extract_clauses_from_chunk(chunk, document_content)
                all_clauses.extend(chunk_clauses)
                
                # Avoid rate limits
                if i < len(chunks) - 1:
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error extracting clauses from chunk {i+1}: {str(e)}")
                continue
        
        # Deduplicate clauses
        unique_clauses = self._deduplicate_clauses(all_clauses)
        
        return unique_clauses
    
    def _extract_clauses_from_chunk(self, text_chunk, document_content):
        """Extract clauses from a text chunk using GPT"""
        prompt = self._create_extraction_prompt(text_chunk)
        
        try:
            # Use the client that was initialized with the environment API key
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a regulatory compliance expert that specializes in identifying regulatory clauses and requirements from documents. Extract all regulatory clauses with their section numbers and titles."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=2000,  # Limit the response size
                timeout=30  # 30-second timeout to prevent hanging
            )
            
            # Extract and parse the response
            response_text = response.choices[0].message.content
            
            try:
                clauses_data = json.loads(response_text)
                
                # Convert to standard format
                clauses = []
                for clause in clauses_data.get("clauses", []):
                    # Skip empty or invalid clauses
                    if not clause.get("text", "").strip():
                        continue
                        
                    clause_obj = {
                        "id": clause.get("id", ""),
                        "section": clause.get("section", ""),
                        "title": clause.get("title", ""),
                        "text": clause.get("text", ""),
                        "requirement_type": clause.get("requirement_type", ""),
                        "source_document": document_content.get("file_name", ""),
                        "page_number": clause.get("page_number", ""),
                    }
                    clauses.append(clause_obj)
                
                return clauses
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON response: {str(e)}")
                logger.error(f"Response text: {response_text}")
                return []
                
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {str(e)}")
            return []
    
    def _create_extraction_prompt(self, text_chunk):
        """Create prompt for extracting clauses"""
        prompt = f"""
Extract all regulatory clauses from the following document text. 
For each clause, identify:
1. The section number if available
2. The title if available
3. The full text of the clause/requirement
4. The type of requirement (mandatory, recommended, informative, etc.)
5. The page number if indicated in the text

Respond with a JSON object with this structure:
{{
  "clauses": [
    {{
      "id": "unique_id",
      "section": "section number",
      "title": "section title",
      "text": "full text of the requirement",
      "requirement_type": "mandatory/recommended/informative",
      "page_number": "page number if available"
    }},
    ...more clauses...
  ]
}}

Only include actual regulatory requirements or clauses, not general information or explanatory text.

Here's the document text:
{text_chunk}
"""
        return prompt
    
    def _split_text_into_chunks(self, text, max_chunk_size=10000, overlap=500):
        """Split text into overlapping chunks to avoid missing clauses at chunk boundaries"""
        if len(text) <= max_chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = min(start + max_chunk_size, len(text))
            
            # Try to find a paragraph break for a cleaner split
            if end < len(text):
                # Look for double newline
                paragraph_break = text.rfind("\n\n", start, end)
                if paragraph_break > start + max_chunk_size // 2:
                    end = paragraph_break + 2
                else:
                    # Look for single newline
                    line_break = text.rfind("\n", start + max_chunk_size // 2, end)
                    if line_break > start + max_chunk_size // 3:
                        end = line_break + 1
            
            chunks.append(text[start:end])
            start = end - overlap  # Create overlap between chunks
            
        return chunks
    
    def _deduplicate_clauses(self, clauses):
        """Remove duplicate clauses based on text similarity"""
        if not clauses:
            return []
        
        unique_clauses = []
        seen_texts = set()
        
        for clause in clauses:
            # Create a normalized version of the text for comparison
            norm_text = re.sub(r'\s+', ' ', clause["text"]).strip().lower()
            
            # Skip if very similar text has been seen
            if norm_text in seen_texts:
                continue
            
            # Check for high similarity with existing clauses
            is_duplicate = False
            for existing_clause in unique_clauses:
                similarity = self._calculate_text_similarity(
                    norm_text, 
                    re.sub(r'\s+', ' ', existing_clause["text"]).strip().lower()
                )
                if similarity > 0.85:  # High similarity threshold
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_clauses.append(clause)
                seen_texts.add(norm_text)
        
        return unique_clauses
    
    def _calculate_text_similarity(self, text1, text2):
        """Calculate simple Jaccard similarity between two texts"""
        if not text1 or not text2:
            return 0
            
        set1 = set(text1.split())
        set2 = set(text2.split())
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0
    