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
                "title": doc.metadata.get("title", "") if doc.metadata else "",
                "author": doc.metadata.get("author", "") if doc.metadata else "",
                "subject": doc.metadata.get("subject", "") if doc.metadata else "",
                "creator": doc.metadata.get("creator", "") if doc.metadata else "",
                "producer": doc.metadata.get("producer", "") if doc.metadata else "",
                "page_count": len(doc),
            }
            
            # Extract text with page numbers - add timeout for large files
            max_pages = 150  # Limit to prevent hanging on huge files
            page_count = min(len(doc), max_pages)
            
            logger.info(f"Processing PDF with {page_count} pages (limited from {len(doc)} total)")
            
            # Process pages in smaller batches to prevent memory issues
            for i in range(page_count):
                try:
                    page = doc[i]
                    page_text = page.get_text()
                    text += f"Page {i+1}:\n{page_text}\n\n"
                    
                    # Free memory for this page
                    page = None
                    
                    # Log progress for large files
                    if i > 0 and i % 10 == 0:
                        logger.info(f"Processed {i}/{page_count} pages from {Path(file_path).name}")
                        
                except Exception as page_error:
                    logger.warning(f"Error extracting text from page {i+1}: {str(page_error)}")
                    text += f"Page {i+1}:\n[Error extracting text from this page]\n\n"
            
            # Check if we limited the pages before closing
            total_pages = len(doc)
            if total_pages > max_pages:
                logger.warning(f"Only processed {max_pages} of {total_pages} pages in {file_path} due to size limits")
                text += f"\n\n[Note: Only {max_pages} of {total_pages} pages processed due to size limits]\n"
                
            # Close the document explicitly
            doc.close()
            
            return {
                "text": text,
                "metadata": metadata,
                "file_path": file_path,
                "file_name": Path(file_path).name
            }
        except Exception as e:
            logger.error(f"Error extracting text from PDF {file_path}: {str(e)}")
            raise
