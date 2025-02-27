# document_processing/extractors/rule_extractor.py
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
import os
import json
import hashlib

logger = logging.getLogger(__name__)

class RuleBasedClauseExtractor:
    """
    Extract regulatory clauses using rule-based approaches like regex patterns
    This is much faster than LLM-based extraction and can be used as an initial filter
    """
    
    def __init__(self):
        # Common section number patterns in regulatory documents
        self.section_patterns = [
            # Section numbers like "1.2.3" or "Section 1.2.3" or "§ 1.2.3" (section symbol)
            r'(?:Section|\§)\s*(\d+(?:\.\d+)*)',
            # Section numbers like "1.2.3." without the word "Section"
            r'(?<!\w)(\d+(?:\.\d+)+)(?:\.\s|\s)',
            # Section numbers with letters like "1.2(a)" or "Section 1.2(a)"
            r'(?:Section|\§)?\s*(\d+(?:\.\d+)*\s*\([a-z]\))',
            # Roman numerals like "IV." or "IV)"
            r'(?<!\w)([IVXivx]+)(?:\.|\))\s',
            # Numbers with parentheses like "(1)" at beginning of line
            r'^\s*\((\d+)\)',
            # Bullets or numbered lists at beginning of lines
            r'^\s*(?:•|\*|\-|\d+\.)\s*(.+)'
        ]
        
        # Common regulatory requirement indicators
        self.requirement_indicators = [
            r'\b(?:shall|must|required|requirement|necessary|mandated|mandatory|essential)\b',
            r'\b(?:should|recommended|desirable|advisable)\b',
            r'\b(?:may|optional|permitted|allowable)\b'
        ]
        
        # Page number detection
        self.page_pattern = r'Page\s+(\d+)\s+of\s+\d+'
        
        # Cache for extracted clauses
        self.clause_cache = {}
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        
    def _extract_section_number(self, text: str) -> Optional[str]:
        """Extract section number from text using regex patterns"""
        for pattern in self.section_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(1)
        return None
    
    def _extract_requirement_type(self, text: str) -> str:
        """Determine requirement type based on language used"""
        text_lower = text.lower()
        
        # Check for mandatory requirements
        if re.search(self.requirement_indicators[0], text_lower):
            return "mandatory"
            
        # Check for recommended requirements
        elif re.search(self.requirement_indicators[1], text_lower):
            return "recommended"
            
        # Check for optional requirements
        elif re.search(self.requirement_indicators[2], text_lower):
            return "optional"
            
        # Default to informative if no clear requirement language
        return "informative"
    
    def _extract_page_number(self, text: str) -> Optional[str]:
        """Extract page number from text"""
        match = re.search(self.page_pattern, text)
        if match:
            return match.group(1)
        return None
    
    def _hash_text(self, text: str) -> str:
        """Create a hash for text to use as cache key"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()
    
    def _get_from_cache(self, text_hash: str) -> Optional[List[Dict[str, Any]]]:
        """Get extracted clauses from cache if available"""
        cache_file = os.path.join(self.cache_dir, f"{text_hash}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error reading from cache: {str(e)}")
        return None
    
    def _save_to_cache(self, text_hash: str, clauses: List[Dict[str, Any]]) -> None:
        """Save extracted clauses to cache"""
        cache_file = os.path.join(self.cache_dir, f"{text_hash}.json")
        try:
            with open(cache_file, 'w') as f:
                json.dump(clauses, f)
        except Exception as e:
            logger.warning(f"Error saving to cache: {str(e)}")
    
    def _split_into_potential_clauses(self, text: str) -> List[Tuple[str, Optional[str]]]:
        """
        Split text into potential regulatory clauses based on section indicators
        Returns list of (text, section_number) tuples
        """
        # Check if document has clear section markers
        has_sections = False
        for pattern in self.section_patterns[:3]:  # Check the first 3 patterns which are most reliable
            if re.search(pattern, text):
                has_sections = True
                break
        
        # If document has clear sections, split by section
        if has_sections:
            # Find all potential section headers
            sections = []
            lines = text.split('\n')
            current_section = None
            current_text = []
            
            for line in lines:
                # Check if line contains a section number
                section_match = None
                for pattern in self.section_patterns:
                    match = re.search(pattern, line)
                    if match:
                        section_match = match
                        break
                
                if section_match:
                    # If we already have a section, add it to our list
                    if current_section and current_text:
                        sections.append((current_section, '\n'.join(current_text)))
                    
                    # Start a new section
                    current_section = line.strip()
                    current_text = []
                else:
                    # Add line to current section text
                    current_text.append(line)
            
            # Add the last section
            if current_section and current_text:
                sections.append((current_section, '\n'.join(current_text)))
            
            # Process each section to extract section number
            result = []
            for section_header, section_text in sections:
                section_number = self._extract_section_number(section_header)
                full_text = f"{section_header}\n{section_text}"
                result.append((full_text, section_number))
            
            return result
        
        # If no clear sections found, try paragraphs
        paragraphs = re.split(r'\n\s*\n', text)
        result = []
        
        for para in paragraphs:
            if len(para.strip()) > 50:  # Ignore very short paragraphs
                section_number = self._extract_section_number(para)
                result.append((para, section_number))
        
        return result
    
    def _extract_title(self, text: str, section_number: Optional[str]) -> str:
        """Extract title from a clause"""
        if not section_number:
            return ""
            
        # Look for section number followed by title
        pattern = f"{re.escape(section_number)}\\s*[.)]?\\s*([A-Z][^.\\n]+)"
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
            
        # Try first line if it's capitalized
        first_line = text.strip().split('\n')[0]
        if section_number in first_line and not first_line.isupper():
            # Remove section number from title
            title = first_line.split(section_number, 1)[1].strip()
            if title.startswith('.') or title.startswith(')'):
                title = title[1:].strip()
            return title
                
        return ""
    
    def extract_clauses(self, document_content: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract clauses from document text using rule-based approach
        
        Args:
            document_content: Dict containing document text and metadata
            
        Returns:
            List of extracted clauses with metadata
        """
        # Check if document_content has the expected format
        if not isinstance(document_content, dict):
            logger.error("Document content is not a dictionary")
            return []
            
        # Get the text from document_content, handling compressed text if needed
        if document_content.get("is_compressed", False):
            # Access text via PDFParser's get_text_from_result method
            # Since we don't have direct access here, we'll handle this differently
            logger.warning("Compressed text detected, but cannot decompress from this class")
            return []
            
        # Get text from the document content
        text = document_content.get("text", "")
        if not text:
            logger.warning("No text found in document content")
            return []
            
        # Check cache first
        text_hash = self._hash_text(text[:5000])  # Use first 5000 chars for hash
        cached_clauses = self._get_from_cache(text_hash)
        if cached_clauses:
            logger.info(f"Using cached extraction results for {document_content.get('file_name', 'unknown')}")
            return cached_clauses
            
        file_name = document_content.get("file_name", "")
        logger.info(f"Extracting clauses using rule-based approach from {file_name}")
        
        # Split text into potential clauses
        potential_clauses = self._split_into_potential_clauses(text)
        
        # Process each potential clause
        clauses = []
        
        for i, (clause_text, section_number) in enumerate(potential_clauses):
            # Skip if text is too short
            if len(clause_text.strip()) < 100:
                continue
                
            # Determine requirement type
            requirement_type = self._extract_requirement_type(clause_text)
            
            # Extract page number
            page_number = self._extract_page_number(clause_text)
            
            # Extract title
            title = self._extract_title(clause_text, section_number)
            
            # Skip if this doesn't look like a regulatory clause
            if requirement_type == "informative" and not section_number:
                # Only include if it has regulatory language
                if not any(re.search(pattern, clause_text.lower()) for pattern in self.requirement_indicators):
                    continue
            
            # Create clause object
            clause_id = f"rule-{file_name}-{i+1}" if file_name else f"rule-{i+1}"
            
            clause = {
                "id": clause_id,
                "section": section_number or "",
                "title": title,
                "text": clause_text.strip(),
                "requirement_type": requirement_type,
                "source_document": file_name,
                "page_number": page_number or "",
                "extraction_method": "rule_based"
            }
            
            clauses.append(clause)
        
        logger.info(f"Extracted {len(clauses)} clauses using rule-based approach from {file_name}")
        
        # Save to cache
        self._save_to_cache(text_hash, clauses)
        
        return clauses