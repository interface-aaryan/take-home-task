# document_processing/extractors/hybrid_extractor.py
import logging
import json
import time
import os
from typing import List, Dict, Any, Optional
import hashlib

from .rule_extractor import RuleBasedClauseExtractor
from .llm_extractor import LLMClauseExtractor

logger = logging.getLogger(__name__)

class HybridClauseExtractor:
    """
    Hybrid approach for extracting regulatory clauses
    Uses rule-based extraction first, then LLM for complex or ambiguous sections
    This balances speed and accuracy while reducing API costs
    """
    
    def __init__(self):
        self.rule_extractor = RuleBasedClauseExtractor()
        self.llm_extractor = LLMClauseExtractor()
        
        # Setup cache
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Threshold for using LLM extraction
        self.confidence_threshold = 0.7  # If rule-based confidence is below this, use LLM
        self.min_clauses_threshold = 5   # Minimum clauses to expect from a regulation document
        
        # Maximum percentage of document to process with LLM (cost control)
        self.max_llm_percentage = 0.3
    
    def _hash_text(self, text: str) -> str:
        """Create a hash for text to use as cache key"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        """Get extracted clauses from cache if available"""
        cache_file = os.path.join(self.cache_dir, f"hybrid_{cache_key}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error reading from hybrid cache: {str(e)}")
        return None
    
    def _save_to_cache(self, cache_key: str, clauses: List[Dict[str, Any]]) -> None:
        """Save extracted clauses to cache"""
        cache_file = os.path.join(self.cache_dir, f"hybrid_{cache_key}.json")
        try:
            with open(cache_file, 'w') as f:
                json.dump(clauses, f)
        except Exception as e:
            logger.warning(f"Error saving to hybrid cache: {str(e)}")
    
    def _assess_rule_extraction_quality(self, rule_clauses: List[Dict[str, Any]], doc_content: Dict[str, Any]) -> float:
        """
        Assess the quality of rule-based extraction
        Returns confidence score between 0 and 1
        """
        if not rule_clauses:
            return 0.0
            
        # Get document metadata
        doc_file_name = doc_content.get("file_name", "")
        is_regulatory = "reg" in doc_file_name.lower() or "cfr" in doc_file_name.lower()
        
        # Check if we got a reasonable number of clauses for a regulatory document
        text_length = len(doc_content.get("text", ""))
        expected_min_clauses = max(5, text_length // 5000)  # Rough estimate
        
        if len(rule_clauses) < expected_min_clauses and is_regulatory:
            return 0.4  # Low confidence for regulatory docs with few clauses
            
        # Check if we have good section number coverage
        sections_with_numbers = sum(1 for c in rule_clauses if c.get("section"))
        section_ratio = sections_with_numbers / len(rule_clauses) if rule_clauses else 0
        
        # Check requirement types
        req_types = [c.get("requirement_type") for c in rule_clauses]
        has_mandatory = "mandatory" in req_types
        has_recommended = "recommended" in req_types
        
        # Calculate confidence score
        confidence = 0.5  # Base confidence
        
        if is_regulatory:
            confidence += 0.1  # Bonus for regulatory documents
            
        if len(rule_clauses) >= expected_min_clauses:
            confidence += 0.1
            
        if section_ratio > 0.7:
            confidence += 0.2
        elif section_ratio > 0.4:
            confidence += 0.1
            
        if has_mandatory and has_recommended:
            confidence += 0.1
            
        return min(confidence, 1.0)
    
    def _identify_ambiguous_sections(self, text: str, rule_clauses: List[Dict[str, Any]]) -> List[str]:
        """
        Identify sections that need LLM processing because rule-based extraction
        might have missed them or processed them poorly
        """
        # Get all sections identified by rule-based extractor
        extracted_sections = set()
        for clause in rule_clauses:
            section = clause.get("section", "")
            if section:
                extracted_sections.add(section)
                
        # Split text into potential sections
        lines = text.split('\n')
        potential_sections = []
        
        for i, line in enumerate(lines):
            # Look for section-like patterns not already extracted
            if any(pattern in line.lower() for pattern in ["section", "requirement", "clause", "§"]):
                # Get context around this line
                start = max(0, i - 2)
                end = min(len(lines), i + 15)
                section_text = '\n'.join(lines[start:end])
                
                # Only include if it doesn't match any already extracted section
                already_extracted = False
                for extracted in extracted_sections:
                    if extracted in section_text:
                        already_extracted = True
                        break
                        
                if not already_extracted and len(section_text.strip()) > 100:
                    potential_sections.append(section_text)
        
        # Limit the number of sections to process with LLM (for cost control)
        max_sections = max(3, int(len(rule_clauses) * self.max_llm_percentage))
        return potential_sections[:max_sections]
    
    def extract_clauses(self, document_content: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract clauses using hybrid approach: rule-based first, then LLM for complex cases
        
        Args:
            document_content: Dict containing document text and metadata
            
        Returns:
            List of extracted clauses with metadata
        """
        file_name = document_content.get("file_name", "unknown")
        logger.info(f"Extracting clauses using hybrid approach from {file_name}")
        
        # Generate cache key based on document
        text = document_content.get("text", "")
        if not text:
            logger.warning("No text found in document content")
            return []
            
        text_hash = self._hash_text(text[:5000])  # Use first 5000 chars for hash
        cache_key = f"{file_name}_{text_hash}"
        
        # Check cache first
        cached_clauses = self._get_from_cache(cache_key)
        if cached_clauses:
            logger.info(f"Using cached hybrid extraction results for {file_name}")
            return cached_clauses
        
        # Step 1: Rule-based extraction (fast)
        rule_clauses = self.rule_extractor.extract_clauses(document_content)
        logger.info(f"Rule-based extraction found {len(rule_clauses)} clauses from {file_name}")
        
        # Step 2: Assess quality of rule-based extraction
        extraction_confidence = self._assess_rule_extraction_quality(rule_clauses, document_content)
        logger.info(f"Rule-based extraction confidence: {extraction_confidence:.2f} for {file_name}")
        
        # Step 3: Decide if LLM extraction is needed
        all_clauses = rule_clauses
        
        if extraction_confidence < self.confidence_threshold:
            # If rule-based confidence is low, find sections that need LLM processing
            ambiguous_sections = self._identify_ambiguous_sections(text, rule_clauses)
            
            # If too few clauses were found and it's a regulatory document
            if len(rule_clauses) < self.min_clauses_threshold and (
                "reg" in file_name.lower() or "cfr" in file_name.lower()
            ):
                logger.info(f"Too few clauses found ({len(rule_clauses)}), using LLM for critical sections")
                
                # Process small chunks of the document with LLM
                # This is expensive but necessary for documents where rule-based extraction failed
                llm_chunks = []
                chunk_size = 5000
                for i in range(0, min(len(text), 20000), chunk_size):
                    llm_chunks.append(text[i:i+chunk_size])
                
                # Combine with identified ambiguous sections
                for section in ambiguous_sections:
                    if section not in llm_chunks:
                        llm_chunks.append(section)
                
                # Process chunks with LLM
                for i, chunk in enumerate(llm_chunks):
                    logger.info(f"Processing chunk {i+1}/{len(llm_chunks)} with LLM")
                    
                    # Create temporary document content for this chunk
                    chunk_content = {
                        "text": chunk,
                        "file_name": file_name,
                        "metadata": document_content.get("metadata", {})
                    }
                    
                    # Extract clauses with LLM
                    llm_clauses = self.llm_extractor.extract_clauses(chunk_content)
                    
                    # Mark as LLM-extracted
                    for clause in llm_clauses:
                        clause["extraction_method"] = "llm"
                    
                    all_clauses.extend(llm_clauses)
                    
                    # Avoid rate limits
                    if i < len(llm_chunks) - 1:
                        time.sleep(1)
            
            # Process ambiguous sections with LLM
            elif ambiguous_sections:
                logger.info(f"Processing {len(ambiguous_sections)} ambiguous sections with LLM")
                
                for i, section in enumerate(ambiguous_sections):
                    # Create temporary document content for this section
                    section_content = {
                        "text": section,
                        "file_name": file_name,
                        "metadata": document_content.get("metadata", {})
                    }
                    
                    # Extract clauses with LLM
                    llm_clauses = self.llm_extractor.extract_clauses(section_content)
                    
                    # Mark as LLM-extracted
                    for clause in llm_clauses:
                        clause["extraction_method"] = "llm"
                    
                    all_clauses.extend(llm_clauses)
                    
                    # Avoid rate limits
                    if i < len(ambiguous_sections) - 1:
                        time.sleep(1)
        
        # Deduplicate clauses
        unique_clauses = self._deduplicate_clauses(all_clauses)
        logger.info(f"Hybrid extraction found {len(unique_clauses)} unique clauses from {file_name}")
        
        # Save to cache
        self._save_to_cache(cache_key, unique_clauses)
        
        return unique_clauses
    
    def _deduplicate_clauses(self, clauses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate clauses based on content similarity"""
        if not clauses:
            return []
            
        unique_clauses = []
        seen_texts = {}
        
        # Sort clauses by extraction method (prefer LLM over rule-based when duplicates exist)
        sorted_clauses = sorted(
            clauses, 
            key=lambda c: 0 if c.get("extraction_method") == "llm" else 1
        )
        
        for clause in sorted_clauses:
            # Create a normalized version of the text for comparison
            text = clause.get("text", "").strip()
            norm_text = ' '.join(text.split()[:30]).lower()  # First 30 words, normalized
            
            # Skip if very similar text has been seen
            if norm_text in seen_texts:
                # If this is an LLM extraction and we have a rule-based one, replace it
                if clause.get("extraction_method") == "llm" and seen_texts[norm_text].get("extraction_method") != "llm":
                    # Remove the rule-based clause
                    unique_clauses = [c for c in unique_clauses if c.get("id") != seen_texts[norm_text].get("id")]
                    # Add the LLM clause
                    unique_clauses.append(clause)
                    seen_texts[norm_text] = clause
                continue
            
            unique_clauses.append(clause)
            seen_texts[norm_text] = clause
        
        return unique_clauses