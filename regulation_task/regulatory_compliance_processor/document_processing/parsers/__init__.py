# document_processing/parsers/__init__.py
from .pdf_parser import PDFParser
from .docx_parser import DocxParser
import logging

logger = logging.getLogger(__name__)

class DocumentParserFactory:
    """Factory for creating document parsers based on file type"""
    
    def __init__(self):
        self.parsers = [
            PDFParser(),
            DocxParser(),
        ]
    
    def get_parser(self, file_path):
        """Get the appropriate parser for the given file"""
        for parser in self.parsers:
            if parser.can_parse(file_path):
                return parser
        
        raise ValueError(f"No parser available for file: {file_path}")
    
    def parse_document(self, file_path):
        """Parse a document using the appropriate parser"""
        try:
            parser = self.get_parser(file_path)
            return parser.extract_text(file_path)
        except Exception as e:
            logger.error(f"Error parsing document {file_path}: {str(e)}")
            raise