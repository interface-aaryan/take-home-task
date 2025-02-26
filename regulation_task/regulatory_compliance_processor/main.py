#!/usr/bin/env python
# main.py
import os
import argparse
import logging
import json
import glob
from pathlib import Path
from typing import List, Dict, Any

from config import REGULATORY_DOCS_DIR, SOP_DIR
from document_processing.parsers import DocumentParserFactory
from document_processing.extractors.llm_extractor import LLMClauseExtractor
from knowledge_base.document_store import DocumentStore
from knowledge_base.vector_store import VectorStore
from analysis.compliance_analyzer import ComplianceAnalyzer

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("regulatory_compliance.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def process_regulatory_documents(docs_dir: str, document_store: DocumentStore, vector_store: VectorStore) -> None:
    """Process regulatory documents and extract clauses"""
    parser_factory = DocumentParserFactory()
    extractor = LLMClauseExtractor()
    
    # Get all PDF and DOCX files in the directory
    doc_files = []
    for ext in ['*.pdf', '*.docx', '*.doc']:
        doc_files.extend(glob.glob(os.path.join(docs_dir, ext)))
    
    logger.info(f"Found {len(doc_files)} regulatory documents to process")
    
    for doc_file in doc_files:
        file_name = os.path.basename(doc_file)
        logger.info(f"Processing regulatory document: {file_name}")
        
        try:
            # Parse document
            doc_content = parser_factory.parse_document(doc_file)
            
            # Add document to document store with version control
            document_id, version_number = document_store.add_document(
                file_name=file_name,
                content=doc_content["text"],
                title=doc_content["metadata"].get("title", ""),
                source="Regulatory Document",
                document_type="Regulation",
                metadata=doc_content["metadata"]
            )
            
            # Extract regulatory clauses
            clauses = extractor.extract_clauses(doc_content)
            
            # Add clauses to document store
            document_store.add_regulatory_clauses(document_id, version_number, clauses)
            
            # Add clauses to vector store for semantic search
            # Add document_id and version to each clause
            for clause in clauses:
                clause["document_id"] = document_id
                clause["document_version"] = version_number
            
            vector_store.add_clauses(clauses)
            
            logger.info(f"Successfully processed {file_name} and extracted {len(clauses)} clauses")
            
        except Exception as e:
            logger.error(f"Error processing document {file_name}: {str(e)}")

def process_sop(sop_file: str, document_store: DocumentStore, vector_store: VectorStore) -> Dict[str, Any]:
    """Process SOP and analyze compliance"""
    parser_factory = DocumentParserFactory()
    analyzer = ComplianceAnalyzer(vector_store=vector_store)
    
    logger.info(f"Processing SOP: {os.path.basename(sop_file)}")
    
    try:
        # Parse SOP document
        sop_content = parser_factory.parse_document(sop_file)
        
        # Analyze SOP compliance
        compliance_results = analyzer.analyze_sop_compliance(sop_content)
        
        return compliance_results
        
    except Exception as e:
        logger.error(f"Error processing SOP {sop_file}: {str(e)}")
        return {
            "error": str(e),
            "status": "failed"
        }

def save_report(report: Dict[str, Any], output_file: str) -> None:
    """Save compliance report to file"""
    try:
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Saved compliance report to {output_file}")
    except Exception as e:
        logger.error(f"Error saving report to {output_file}: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="Regulatory Compliance Document Processor")
    parser.add_argument("--sop", type=str, help="Path to SOP document", default=os.path.join(SOP_DIR, "sop.pdf"))
    parser.add_argument("--reg-docs", type=str, help="Path to directory containing regulatory documents", default=REGULATORY_DOCS_DIR)
    parser.add_argument("--output", type=str, help="Path to output report file", default="compliance_report.json")
    parser.add_argument("--rebuild-kb", action="store_true", help="Rebuild knowledge base from scratch")
    args = parser.parse_args()
    
    logger.info("Starting Regulatory Compliance Document Processor")
    
    # Initialize document store and vector store
    document_store = DocumentStore()
    vector_store = VectorStore()
    
    # Process regulatory documents if needed
    if args.rebuild_kb:
        logger.info("Rebuilding knowledge base from regulatory documents")
        process_regulatory_documents(args.reg_docs, document_store, vector_store)
    else:
        # Check if knowledge base already has documents
        stats = vector_store.get_stats()
        if stats["total_clauses"] == 0:
            logger.info("Knowledge base is empty, processing regulatory documents")
            process_regulatory_documents(args.reg_docs, document_store, vector_store)
        else:
            logger.info(f"Using existing knowledge base with {stats['total_clauses']} clauses")
    
    # Process SOP and analyze compliance
    compliance_report = process_sop(args.sop, document_store, vector_store)
    
    # Save report
    save_report(compliance_report, args.output)
    
    logger.info("Regulatory Compliance Document Processor completed successfully")

if __name__ == "__main__":
    main()
    