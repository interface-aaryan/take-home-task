# document_processing/parsers/pdf_parser.py
import fitz  # PyMuPDF
import PyPDF2  # More lightweight for initial parsing
from pathlib import Path
import logging
import re
import os
import zlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile

logger = logging.getLogger(__name__)

class PDFParser:
    """Optimized parser for PDF documents"""
    
    def __init__(self):
        self.supported_extensions = ['.pdf']
        self.batch_size = 10  # Process pages in batches
        self.max_pages = 200  # Higher limit with optimized processing
        self.min_content_length = 100  # Min characters for a page to be considered content
        self.skip_patterns = [
            r'^(?:\s*|.*copyright.*|.*all\s+rights\s+reserved.*|.*confidential.*|.*table\s+of\s+contents.*|.*index.*)$',
            r'^page\s+\d+\s+of\s+\d+$'
        ]
        
    def can_parse(self, file_path):
        """Check if the file can be parsed with this parser"""
        return Path(file_path).suffix.lower() in self.supported_extensions
    
    def _is_content_page(self, text):
        """Check if a page contains actual content vs. blank/cover/TOC pages"""
        if len(text.strip()) < self.min_content_length:
            return False
            
        # Check against skip patterns
        text_lower = text.lower()
        for pattern in self.skip_patterns:
            if re.match(pattern, text_lower, re.IGNORECASE | re.DOTALL):
                return False
                
        return True
        
    def _get_quick_metadata(self, file_path):
        """Get basic metadata quickly using PyPDF2"""
        try:
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                return {
                    "page_count": len(reader.pages),
                    "title": reader.metadata.get('/Title', '') if reader.metadata else '',
                }
        except Exception as e:
            logger.warning(f"Error getting quick metadata: {str(e)}")
            return {"page_count": 0, "title": ""}
            
    def _process_page_batch(self, doc, start_idx, end_idx):
        """Process a batch of pages in parallel"""
        result_text = ""
        valid_pages = 0
        
        for i in range(start_idx, min(end_idx, len(doc))):
            try:
                page = doc[i]
                page_text = page.get_text()
                
                # Check if page has actual content
                if self._is_content_page(page_text):
                    result_text += f"Page {i+1}:\n{page_text}\n\n"
                    valid_pages += 1
                else:
                    logger.debug(f"Skipping page {i+1} - insufficient content")
                
                # Free memory
                page = None
                
            except Exception as page_error:
                logger.warning(f"Error extracting text from page {i+1}: {str(page_error)}")
                result_text += f"Page {i+1}:\n[Error extracting text from this page]\n\n"
                
        return result_text, valid_pages
    
    def _compress_text(self, text):
        """Compress text to reduce memory usage"""
        try:
            compressed = zlib.compress(text.encode('utf-8'))
            return compressed
        except Exception as e:
            logger.warning(f"Error compressing text: {str(e)}")
            return text.encode('utf-8')
    
    def _decompress_text(self, compressed_data):
        """Decompress text"""
        try:
            if isinstance(compressed_data, bytes):
                return zlib.decompress(compressed_data).decode('utf-8')
            return compressed_data  # Not compressed
        except Exception as e:
            logger.warning(f"Error decompressing text: {str(e)}")
            return str(compressed_data)  # Return as string
            
    def extract_text(self, file_path):
        """Extract text from a PDF file with optimized processing"""
        start_time = threading.Event()
        start_time.set()  # For timing
        
        try:
            # Quick check of file size
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            logger.info(f"Processing PDF {Path(file_path).name} ({file_size_mb:.2f} MB)")
            
            # Get quick metadata first using lighter PyPDF2
            quick_metadata = self._get_quick_metadata(file_path)
            total_pages = quick_metadata.get("page_count", 0)
            
            if total_pages == 0:
                # Fallback to PyMuPDF for metadata if PyPDF2 fails
                doc = fitz.open(file_path)
                total_pages = len(doc)
                doc.close()
            
            logger.info(f"PDF has {total_pages} pages")
            
            # For very large files, use more aggressive optimization
            is_large_file = file_size_mb > 10 or total_pages > 100
            max_pages = min(self.max_pages, total_pages)
            
            # Open document with PyMuPDF for text extraction
            doc = fitz.open(file_path)
            
            # Get full metadata only for smaller files
            metadata = quick_metadata
            if not is_large_file:
                metadata = {
                    "title": doc.metadata.get("title", "") if doc.metadata else "",
                    "author": doc.metadata.get("author", "") if doc.metadata else "",
                    "subject": doc.metadata.get("subject", "") if doc.metadata else "",
                    "creator": doc.metadata.get("creator", "") if doc.metadata else "",
                    "producer": doc.metadata.get("producer", "") if doc.metadata else "",
                    "page_count": total_pages,
                }
            
            # Process pages in parallel batches
            all_text = ""
            valid_pages = 0
            processed_pages = 0
            
            # Use ThreadPoolExecutor for parallel processing
            with ThreadPoolExecutor(max_workers=min(os.cpu_count(), 4)) as executor:
                futures = []
                
                # Submit batches of pages for processing
                for start_idx in range(0, max_pages, self.batch_size):
                    end_idx = min(start_idx + self.batch_size, max_pages)
                    futures.append(
                        executor.submit(self._process_page_batch, doc, start_idx, end_idx)
                    )
                
                # Collect results as they complete
                for future in as_completed(futures):
                    batch_text, batch_valid_pages = future.result()
                    all_text += batch_text
                    valid_pages += batch_valid_pages
                    processed_pages += self.batch_size
                    
                    # Log progress
                    logger.info(f"Processed approximately {min(processed_pages, max_pages)}/{max_pages} pages "
                               f"({valid_pages} with content) from {Path(file_path).name}")
            
            # Check if we limited the pages before closing
            if total_pages > max_pages:
                logger.warning(f"Only processed {max_pages} of {total_pages} pages in {file_path} due to size limits")
                all_text += f"\n\n[Note: Only {max_pages} of {total_pages} pages processed due to size limits]\n"
            
            # Close the document explicitly
            doc.close()
            
            # For very large texts, compress to save memory
            if len(all_text) > 1_000_000:  # 1MB of text
                logger.info(f"Compressing large text ({len(all_text)} chars) from {Path(file_path).name}")
                compressed_text = self._compress_text(all_text)
                
                # Create temporary file to store compressed data if needed
                if len(all_text) > 5_000_000:  # 5MB
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zlib')
                    temp_file.write(compressed_text)
                    temp_file_path = temp_file.name
                    temp_file.close()
                    
                    logger.info(f"Text too large, saved to temporary file: {temp_file_path}")
                    
                    return {
                        "text": f"[LARGE TEXT STORED IN TEMP FILE: {temp_file_path}]",
                        "text_file_path": temp_file_path,
                        "is_compressed": True,
                        "metadata": metadata,
                        "file_path": file_path,
                        "file_name": Path(file_path).name,
                        "valid_pages": valid_pages,
                        "total_processed": min(total_pages, max_pages)
                    }
                
                return {
                    "text": compressed_text,
                    "is_compressed": True,
                    "metadata": metadata,
                    "file_path": file_path,
                    "file_name": Path(file_path).name,
                    "valid_pages": valid_pages,
                    "total_processed": min(total_pages, max_pages)
                }
            
            return {
                "text": all_text,
                "is_compressed": False,
                "metadata": metadata,
                "file_path": file_path,
                "file_name": Path(file_path).name,
                "valid_pages": valid_pages,
                "total_processed": min(total_pages, max_pages)
            }
            
        except Exception as e:
            logger.error(f"Error extracting text from PDF {file_path}: {str(e)}")
            raise
            
    def get_text_from_result(self, result):
        """Get text from result, handling compression if needed"""
        if not result:
            return ""
            
        # Check if text is in a temporary file
        if isinstance(result.get("text"), str) and result.get("text").startswith("[LARGE TEXT STORED IN TEMP FILE:"):
            temp_file_path = result.get("text_file_path")
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    with open(temp_file_path, "rb") as f:
                        compressed_data = f.read()
                    return self._decompress_text(compressed_data)
                except Exception as e:
                    logger.error(f"Error reading text from temp file: {str(e)}")
                    return f"[Error reading from temp file: {str(e)}]"
        
        # Handle compressed text
        if result.get("is_compressed", False):
            return self._decompress_text(result.get("text", ""))
            
        # Return regular text
        return result.get("text", "")
