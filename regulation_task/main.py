#!/usr/bin/env python
import sys
import os
import gc
import argparse
import logging
import json
import glob
import time
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

# Configure logging for this main file
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "regulatory_compliance_processor", "logs", "main.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
# Ensure that all loggers propagate to the root logger
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).propagate = True

logger = logging.getLogger(__name__)

# Add the project root directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import regulatory processor modules
from regulatory_compliance_processor.config import (
    REGULATORY_DOCS_DIR, SOP_DIR, MAX_WORKERS, PROCESSING_TIMEOUT,
    USE_RULE_BASED_EXTRACTION, USE_HYBRID_EXTRACTION, USE_PARALLEL_PROCESSING,
    COMPRESS_LARGE_TEXTS, EMBEDDING_BATCH_SIZE, PROCESSING_BATCH_SIZE,
    USE_LANGCHAIN, USE_TEXT_PREPROCESSING
)
from regulatory_compliance_processor.document_processing.parsers import DocumentParserFactory
from regulatory_compliance_processor.document_processing.parsers.pdf_parser import PDFParser
from regulatory_compliance_processor.document_processing.extractors.llm_extractor import LLMClauseExtractor
from regulatory_compliance_processor.document_processing.extractors.rule_extractor import RuleBasedClauseExtractor
from regulatory_compliance_processor.document_processing.extractors.hybrid_extractor import HybridClauseExtractor
from regulatory_compliance_processor.knowledge_base.document_store import DocumentStore
from regulatory_compliance_processor.knowledge_base.vector_store_factory import VectorStoreFactory
from regulatory_compliance_processor.analysis.compliance_analyzer import ComplianceAnalyzer

def process_single_document(doc_file: str, 
                            document_store: DocumentStore, 
                            vector_store: Any,
                            processed_docs: Dict,
                            checkpoint_file: str) -> Dict[str, Any]:
    """Process a single regulatory document and return results"""
    file_name = os.path.basename(doc_file)
    
    # Skip if already processed successfully
    if file_name in processed_docs and processed_docs[file_name].get("status") == "completed":
        logger.info(f"Skipping already processed document: {file_name}")
        return {"file_name": file_name, "status": "skipped"}
    
    logger.info(f"Processing regulatory document: {file_name} (Size: {os.path.getsize(doc_file)/1024/1024:.2f} MB)")
    
    # Track processing time
    start_time = time.time()
    
    try:
        # Clean memory before processing document
        gc.collect()
        
        # Initialize parser based on file type
        parser_factory = DocumentParserFactory()
        
        # Parse document with optimized parser
        logger.info(f"Parsing document: {file_name}")
        doc_content = parser_factory.parse_document(doc_file)
        
        # Check if we need to handle compressed text
        if isinstance(doc_content, dict) and doc_content.get("is_compressed", False):
            logger.info(f"Document has compressed text, decompressing: {file_name}")
            if isinstance(doc_content.get("text"), bytes):
                # This would be handled by PDFParser's get_text_from_result in a normal flow
                # For now, just log it
                logger.info(f"Document text is compressed binary, handling appropriately")
                
                # Get text using the PDF parser
                pdf_parser = PDFParser()
                doc_text = pdf_parser.get_text_from_result(doc_content)
                doc_content["text"] = doc_text
                doc_content["is_compressed"] = False
        
        # Get basic document info
        doc_text = doc_content.get("text", "")
        doc_metadata = doc_content.get("metadata", {})
        
        # Log successful parsing
        logger.info(f"Successfully parsed document: {file_name} - Text length: {len(doc_text)} chars")
        
        # Add document to document store with version control
        document_id, version_number = document_store.add_document(
            file_name=file_name,
            content=doc_text,
            title=doc_metadata.get("title", ""),
            source="Regulatory Document",
            document_type="Regulation",
            metadata=doc_metadata
        )
        
        # Update checkpoint with document processing started
        processed_docs[file_name] = {"status": "processing", "document_id": document_id, "version": version_number}
        with open(checkpoint_file, 'w') as f:
            json.dump(processed_docs, f)
        
        # Extract regulatory clauses using appropriate extractor
        logger.info(f"Extracting clauses from {file_name}")
        
        # Choose the appropriate extractor based on configuration
        if USE_HYBRID_EXTRACTION:
            logger.info(f"Using hybrid extractor for {file_name}")
            extractor = HybridClauseExtractor()
            clauses = extractor.extract_clauses(doc_content)
        elif USE_RULE_BASED_EXTRACTION:
            logger.info(f"Using rule-based extractor for {file_name}")
            extractor = RuleBasedClauseExtractor()
            clauses = extractor.extract_clauses(doc_content)
        else:
            logger.info(f"Using LLM extractor for {file_name}")
            extractor = LLMClauseExtractor()
            clauses = extractor.extract_clauses(doc_content)
            
        logger.info(f"Extracted {len(clauses)} clauses from {file_name}")
        
        # Free memory
        doc_text = None
        doc_content = None
        extractor = None
        gc.collect()
        
        # Add clauses to document store
        logger.info(f"Adding clauses to document store for {file_name}")
        document_store.add_regulatory_clauses(document_id, version_number, clauses)
        
        # Add clauses to vector store in smaller batches for semantic search
        logger.info(f"Adding clauses to vector store in batches for {file_name}")
        batch_size = EMBEDDING_BATCH_SIZE
        
        for i in range(0, len(clauses), batch_size):
            batch_clauses = clauses[i:i+batch_size]
            
            # Add document_id and version to each clause
            for clause in batch_clauses:
                clause["document_id"] = document_id
                clause["document_version"] = version_number
            
            # Add to vector store
            vector_store.add_clauses(batch_clauses)
            logger.info(f"Added batch {i//batch_size + 1}/{(len(clauses) + batch_size - 1)//batch_size} of clauses to vector store for {file_name}")
            
            # Force memory cleanup between batches
            gc.collect()
        
        # Mark document as completed in checkpoint
        elapsed_time = time.time() - start_time
        
        result = {
            "status": "completed", 
            "document_id": document_id, 
            "version": version_number, 
            "clauses": len(clauses),
            "elapsed_time": elapsed_time,
            "completed_at": datetime.now().isoformat()
        }
        
        processed_docs[file_name] = result
        with open(checkpoint_file, 'w') as f:
            json.dump(processed_docs, f)
        
        logger.info(f"Successfully processed {file_name} and extracted {len(clauses)} clauses in {elapsed_time:.2f} seconds")
        
        # Final cleanup - store clauses length before setting to None
        clauses_length = len(clauses) if clauses is not None else 0
        clauses = None
        gc.collect()
        
        return {"file_name": file_name, "status": "completed", "document_id": document_id, "clauses": clauses_length}
        
    except Exception as e:
        logger.error(f"Error processing document {file_name}: {str(e)}")
        # Mark document as failed in checkpoint
        processed_docs[file_name] = {
            "status": "failed", 
            "error": str(e),
            "failed_at": datetime.now().isoformat()
        }
        with open(checkpoint_file, 'w') as f:
            json.dump(processed_docs, f)
        
        # Force memory cleanup after error
        gc.collect()
        
        return {"file_name": file_name, "status": "failed", "error": str(e)}

def process_regulatory_documents(docs_dir: str, document_store: DocumentStore, vector_store: Any) -> None:
    """Process regulatory documents with optimized parallel processing and memory management"""
    # Get all PDF and DOCX files in the directory
    doc_files = []
    for ext in ['*.pdf', '*.docx', '*.doc']:
        doc_files.extend(glob.glob(os.path.join(docs_dir, ext)))
    
    # Sort files by size (process smaller files first)
    doc_files.sort(key=lambda x: os.path.getsize(x))
    
    logger.info(f"Found {len(doc_files)} regulatory documents to process")
    
    # Create checkpoint file to track processed documents
    checkpoint_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "regulatory_compliance_processor", "data")
    os.makedirs(checkpoint_dir, exist_ok=True)
    checkpoint_file = os.path.join(checkpoint_dir, "processing_checkpoint.json")
    processed_docs = {}
    
    # Load checkpoint if exists
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r') as f:
                processed_docs = json.load(f)
            logger.info(f"Loaded checkpoint with {len(processed_docs)} processed documents")
        except Exception as e:
            logger.error(f"Error loading checkpoint: {str(e)}")
    
    # Determine whether to use parallel processing
    if USE_PARALLEL_PROCESSING and len(doc_files) > 1:
        logger.info(f"Using parallel processing with {MAX_WORKERS} workers")
        
        # Process documents in smaller batches to control memory usage
        batch_size = PROCESSING_BATCH_SIZE
        batches = [doc_files[i:i+batch_size] for i in range(0, len(doc_files), batch_size)]
        
        # Process each batch
        for batch_idx, batch in enumerate(batches):
            logger.info(f"Processing batch {batch_idx+1}/{len(batches)} of {len(batch)} documents")
            
            # Process this batch in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {}
                
                # Submit jobs to executor
                for doc_file in batch:
                    # Skip if already processed successfully
                    file_name = os.path.basename(doc_file)
                    if file_name in processed_docs and processed_docs[file_name].get("status") == "completed":
                        logger.info(f"Skipping already processed document: {file_name}")
                        continue
                        
                    # Submit processing job
                    futures[executor.submit(
                        process_single_document, 
                        doc_file, 
                        document_store, 
                        vector_store, 
                        processed_docs,
                        checkpoint_file
                    )] = file_name
                
                # Process results as they complete
                for future in concurrent.futures.as_completed(futures):
                    file_name = futures[future]
                    try:
                        result = future.result(timeout=PROCESSING_TIMEOUT)
                        logger.info(f"Completed processing {file_name}: {result.get('status')}")
                    except concurrent.futures.TimeoutError:
                        logger.error(f"Processing {file_name} timed out after {PROCESSING_TIMEOUT} seconds")
                    except Exception as e:
                        logger.error(f"Error processing {file_name}: {str(e)}")
            
            # Force cleanup after each batch
            gc.collect()
            
            # Log progress after each batch
            completed = sum(1 for d in processed_docs.values() if d.get("status") == "completed")
            logger.info(f"Progress: {completed}/{len(doc_files)} documents processed ({completed/len(doc_files)*100:.1f}%)")
            
    else:
        # Process documents sequentially
        logger.info("Using sequential processing")
        
        for doc_file in doc_files:
            result = process_single_document(
                doc_file, 
                document_store, 
                vector_store, 
                processed_docs,
                checkpoint_file
            )
            logger.info(f"Document {result.get('file_name')}: {result.get('status')}")
            
            # Force memory cleanup after each document
            gc.collect()
    
    # Calculate and log final statistics
    stats = {
        "total": len(doc_files),
        "completed": sum(1 for d in processed_docs.values() if d.get("status") == "completed"),
        "failed": sum(1 for d in processed_docs.values() if d.get("status") == "failed"),
        "total_clauses": sum(d.get("clauses", 0) for d in processed_docs.values()),
    }
    
    logger.info(f"Document processing completed: {stats['completed']}/{stats['total']} documents processed, {stats['total_clauses']} clauses extracted")
    
    # Analyze any failures
    if stats["failed"] > 0:
        failures = [name for name, info in processed_docs.items() if info.get("status") == "failed"]
        logger.warning(f"Failed documents: {', '.join(failures)}")

def process_sop(sop_file: str, document_store: DocumentStore, vector_store: Any) -> Dict[str, Any]:
    """Process SOP and analyze compliance with optimized methods"""
    parser_factory = DocumentParserFactory()
    analyzer = ComplianceAnalyzer(vector_store=vector_store)
    
    logger.info(f"Processing SOP: {os.path.basename(sop_file)}")
    
    try:
        # Parse SOP document with optimized parser
        sop_content = parser_factory.parse_document(sop_file)
        
        # Check if we need to handle compressed text
        if isinstance(sop_content, dict) and sop_content.get("is_compressed", False):
            logger.info(f"SOP document has compressed text, decompressing")
            pdf_parser = PDFParser()
            sop_text = pdf_parser.get_text_from_result(sop_content)
            sop_content["text"] = sop_text
            sop_content["is_compressed"] = False
        
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
        # If output_file is not an absolute path, make it relative to the reports directory
        if not os.path.isabs(output_file):
            output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", os.path.basename(output_file))
        
        # Ensure reports directory exists
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Saved compliance report to {output_file}")
    except Exception as e:
        logger.error(f"Error saving report to {output_file}: {str(e)}")

def print_system_info():
    """Print system information for diagnostics"""
    try:
        import platform
        import psutil
        
        # Get system info
        system_info = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(logical=False),
            "logical_cpus": psutil.cpu_count(logical=True),
            "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
            "available_memory_gb": round(psutil.virtual_memory().available / (1024**3), 2)
        }
        
        logger.info("System Information:")
        for key, value in system_info.items():
            logger.info(f"  - {key}: {value}")
            
    except ImportError:
        logger.info("System information not available (psutil not installed)")

def main():
    parser = argparse.ArgumentParser(description="Regulatory Compliance Document Processor")
    parser.add_argument("--sop", type=str, help="Path to SOP document", default=os.path.join(SOP_DIR, "original.docx"))
    parser.add_argument("--reg-docs", type=str, help="Path to directory containing regulatory documents", default=REGULATORY_DOCS_DIR)
    parser.add_argument("--output", type=str, help="Path to output report file", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "compliance_report.json"))
    parser.add_argument("--rebuild-kb", action="store_true", help="Rebuild knowledge base from scratch")
    parser.add_argument("--build-only", action="store_true", help="Only build knowledge base, don't process SOP")
    parser.add_argument("--optimize", action="store_true", help="Use optimized processing methods")
    parser.add_argument("--use-langchain", action="store_true", help="Use LangChain with ChromaDB instead of FAISS")
    parser.add_argument("--use-smaller-models", action="store_true", help="Use smaller embedding models for faster processing")
    args = parser.parse_args()
    
    logger.info("Starting Regulatory Compliance Document Processor")
    
    # Print system information
    print_system_info()
    
    try:
        # Cleanup memory before starting
        gc.collect()
        logger.info(f"Starting with clean memory state")
        
        # Override config settings with command line arguments
        use_langchain = args.use_langchain if args.use_langchain else USE_LANGCHAIN
        
        # Initialize document store and vector store
        document_store = DocumentStore()
        vector_store = VectorStoreFactory.create_vector_store(use_langchain=use_langchain)
        
        # Process regulatory documents if needed
        kb_updated = False
        
        if args.rebuild_kb:
            logger.info("Rebuilding knowledge base from regulatory documents")
            process_regulatory_documents(args.reg_docs, document_store, vector_store)
            kb_updated = True
        else:
            # Check if knowledge base already has documents
            stats = vector_store.get_stats()
            if stats.get("total_clauses", 0) == 0:
                logger.info("Knowledge base is empty, processing regulatory documents")
                process_regulatory_documents(args.reg_docs, document_store, vector_store)
                kb_updated = True
            else:
                logger.info(f"Using existing knowledge base with {stats.get('total_clauses', 0)} clauses")
        
        # Clean up memory after building knowledge base
        gc.collect()
        
        # Skip SOP processing if only building knowledge base
        if args.build_only:
            logger.info("Knowledge base build completed, skipping SOP processing (--build-only flag set)")
            return
        
        # Process SOP and analyze compliance
        if os.path.exists(args.sop):
            logger.info(f"Processing SOP: {args.sop}")
            compliance_report = process_sop(args.sop, document_store, vector_store)
            
            # Save report
            save_report(compliance_report, args.output)
            logger.info(f"Saved compliance report to {args.output}")
        else:
            logger.error(f"SOP file not found: {args.sop}")
            return
        
        logger.info("Regulatory Compliance Document Processor completed successfully")
        
    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()