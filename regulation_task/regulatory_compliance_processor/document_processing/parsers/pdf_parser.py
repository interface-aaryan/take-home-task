# document_processing/parsers/pdf_parser.py
import fitz  # PyMuPDF
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class PDFParser:
    """Parser for PDF documents"""
    
    def __init__(self):
        self.supported_extensions = ['.pdf']
        
    def can_parse(self, file_path):
        """Check if the file can be parsed with this parser"""
        return Path(file_path).suffix.lower() in self.supported_extensions
    
    def extract_text(self, file_path):
        """Extract text from a PDF file"""
        try:
            doc = fitz.open(file_path)
            text = ""
            metadata = {
                "title": doc.metadata.get("title", ""),
                "author": doc.metadata.get("author", ""),
                "subject": doc.metadata.get("subject", ""),
                "creator": doc.metadata.get("creator", ""),
                "producer": doc.metadata.get("producer", ""),
                "page_count": len(doc),
            }
            
            # Extract text with page numbers
            for i, page in enumerate(doc):
                page_text = page.get_text()
                text += f"Page {i+1}:\n{page_text}\n\n"
            
            return {
                "text": text,
                "metadata": metadata,
                "file_path": file_path,
                "file_name": Path(file_path).name
            }
        except Exception as e:
            logger.error(f"Error extracting text from PDF {file_path}: {str(e)}")
            raise
