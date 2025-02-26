#!/usr/bin/env python
# regulatory_compliance_processor/main.py
import os
import argparse
import logging
import json
import glob
import gc
from pathlib import Path
from typing import List, Dict, Any

from regulatory_compliance_processor.config import REGULATORY_DOCS_DIR, SOP_DIR
from regulatory_compliance_processor.document_processing.parsers import DocumentParserFactory
from regulatory_compliance_processor.document_processing.extractors.llm_extractor import LLMClauseExtractor
from regulatory_compliance_processor.knowledge_base.document_store import DocumentStore
from regulatory_compliance_processor.knowledge_base.vector_store import VectorStore
from regulatory_compliance_processor.analysis.compliance_analyzer import ComplianceAnalyzer

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("regulatory_compliance.log"),
        logging.StreamHandler()
    ]
)
# Ensure that all loggers propagate to the root logger
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).propagate = True

logger = logging.getLogger(__name__)

def process_regulatory_documents(docs_dir: str, document_store: DocumentStore, vector_store: VectorStore) -> None:
    """Process regulatory documents one at a time with checkpointing"""
    parser_factory = DocumentParserFactory()
    extractor = LLMClauseExtractor()
    
    # Get all PDF and DOCX files in the directory
    doc_files = []
    for ext in ['*.pdf', '*.docx', '*.doc']:
        doc_files.extend(glob.glob(os.path.join(docs_dir, ext)))
    
    # Sort files by size (process smaller files first)
    doc_files.sort(key=lambda x: os.path.getsize(x))
    
    logger.info(f"Found {len(doc_files)} regulatory documents to process")
    
    # Create checkpoint file to track processed documents
    checkpoint_file = os.path.join(os.path.dirname(docs_dir), "processing_checkpoint.json")
    processed_docs = {}
    
    # Load checkpoint if exists
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r') as f:
                processed_docs = json.load(f)
            logger.info(f"Loaded checkpoint with {len(processed_docs)} processed documents")
        except Exception as e:
            logger.error(f"Error loading checkpoint: {str(e)}")
    
    # Process one document at a time
    for doc_file in doc_files:
        file_name = os.path.basename(doc_file)
        
        # Skip if already processed successfully
        if file_name in processed_docs and processed_docs[file_name].get("status") == "completed":
            logger.info(f"Skipping already processed document: {file_name}")
            continue
            
        logger.info(f"Processing regulatory document: {file_name} (Size: {os.path.getsize(doc_file)/1024/1024:.2f} MB)")
        
        try:
            # Clean memory before processing each document
            gc.collect()
            
            # Parse document
            doc_content = parser_factory.parse_document(doc_file)
            
            # Free memory after parsing
            doc_text = doc_content.get("text", "")
            doc_metadata = doc_content.get("metadata", {})
            doc_file_name = doc_content.get("file_name", file_name)
            
            # Remove the original doc_content to save memory
            doc_content = None
            gc.collect()
            
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
            
            # Recreate doc_content with minimal information for clause extraction
            minimal_doc_content = {
                "text": doc_text,
                "file_name": file_name,
                "metadata": {
                    "title": doc_metadata.get("title", "")
                }
            }
            
            # Extract regulatory clauses
            logger.info(f"Extracting clauses from {file_name}")
            
            # Split text into smaller chunks to prevent memory issues
            max_chunk_size = 3000
            text_length = len(doc_text)
            
            # If document is too large, process it in chunks
            all_clauses = []
            
            if text_length > 10000:  # Only chunk large documents
                logger.info(f"Document is large ({text_length} chars), processing in chunks")
                
                # Process in chunks of max_chunk_size with overlap
                chunk_size = max_chunk_size
                overlap = 500
                
                for start_idx in range(0, text_length, chunk_size - overlap):
                    end_idx = min(start_idx + chunk_size, text_length)
                    
                    # Extract chunk
                    chunk_text = doc_text[start_idx:end_idx]
                    chunk_content = {
                        "text": chunk_text,
                        "file_name": file_name,
                        "metadata": minimal_doc_content["metadata"]
                    }
                    
                    # Process chunk
                    logger.info(f"Processing chunk {start_idx//chunk_size + 1}/{(text_length + chunk_size - 1)//chunk_size} from {file_name}")
                    try:
                        chunk_clauses = extractor.extract_clauses(chunk_content)
                        all_clauses.extend(chunk_clauses)
                        
                        # Force cleanup
                        chunk_content = None
                        chunk_text = None
                        gc.collect()
                    except Exception as chunk_e:
                        logger.error(f"Error processing chunk {start_idx//chunk_size + 1}: {str(chunk_e)}")
            else:
                # Process the whole document at once for smaller documents
                try:
                    all_clauses = extractor.extract_clauses(minimal_doc_content)
                except Exception as e:
                    logger.error(f"Error extracting clauses: {str(e)}")
            
            # Free document text to save memory
            doc_text = None
            minimal_doc_content = None
            gc.collect()
            
            # Deduplicate clauses
            logger.info(f"Deduplicating {len(all_clauses)} extracted clauses")
            unique_clauses = []
            seen_texts = set()
            
            for clause in all_clauses:
                # Simple deduplication based on text
                norm_text = clause["text"].strip()[:100]  # Use prefix for deduplication
                if norm_text not in seen_texts:
                    unique_clauses.append(clause)
                    seen_texts.add(norm_text)
            
            logger.info(f"Found {len(unique_clauses)} unique clauses after deduplication")
            
            # Free original clauses to save memory
            all_clauses = None
            seen_texts = None
            gc.collect()
            
            # Add clauses to document store
            logger.info(f"Adding clauses to document store")
            document_store.add_regulatory_clauses(document_id, version_number, unique_clauses)
            
            # Add clauses to vector store in smaller batches for semantic search
            logger.info(f"Adding clauses to vector store in batches")
            batch_size = 20  # Process 20 clauses at a time to reduce memory usage
            
            for i in range(0, len(unique_clauses), batch_size):
                batch_clauses = unique_clauses[i:i+batch_size]
                
                # Add document_id and version to each clause
                for clause in batch_clauses:
                    clause["document_id"] = document_id
                    clause["document_version"] = version_number
                
                # Add to vector store
                vector_store.add_clauses(batch_clauses)
                logger.info(f"Added batch {i//batch_size + 1}/{(len(unique_clauses) + batch_size - 1)//batch_size} of clauses to vector store")
                
                # Force memory cleanup between batches
                gc.collect()
            
            # Mark document as completed in checkpoint
            processed_docs[file_name] = {
                "status": "completed", 
                "document_id": document_id, 
                "version": version_number, 
                "clauses": len(unique_clauses)
            }
            with open(checkpoint_file, 'w') as f:
                json.dump(processed_docs, f)
            
            logger.info(f"Successfully processed {file_name} and extracted {len(unique_clauses)} clauses")
            
            # Final cleanup
            unique_clauses = None
            gc.collect()
            
        except Exception as e:
            logger.error(f"Error processing document {file_name}: {str(e)}")
            # Mark document as failed in checkpoint
            processed_docs[file_name] = {"status": "failed", "error": str(e)}
            with open(checkpoint_file, 'w') as f:
                json.dump(processed_docs, f)
        
        # Force memory cleanup after each document
        gc.collect()
        
        # Log memory status
        logger.info(f"Memory status after processing {file_name}")
        
        # Always save progress after each document
        logger.info(f"Progress: {sum(1 for d in processed_docs.values() if d.get('status') == 'completed')}/{len(doc_files)} documents processed")

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
    parser.add_argument("--sop", type=str, help="Path to SOP document", default=os.path.join(SOP_DIR, "original.docx"))
    parser.add_argument("--reg-docs", type=str, help="Path to directory containing regulatory documents", default=REGULATORY_DOCS_DIR)
    parser.add_argument("--output", type=str, help="Path to output report file", default="compliance_report.json")
    parser.add_argument("--rebuild-kb", action="store_true", help="Rebuild knowledge base from scratch")
    parser.add_argument("--build-only", action="store_true", help="Only build knowledge base, don't process SOP")
    args = parser.parse_args()
    
    logger.info("Starting Regulatory Compliance Document Processor")
    
    # Initialize document store and vector store
    document_store = DocumentStore()
    vector_store = VectorStore()
    
    # Process regulatory documents if needed
    kb_updated = False
    
    if args.rebuild_kb:
        logger.info("Rebuilding knowledge base from regulatory documents")
        process_regulatory_documents(args.reg_docs, document_store, vector_store)
        kb_updated = True
    else:
        # Check if knowledge base already has documents
        stats = vector_store.get_stats()
        if stats["total_clauses"] == 0:
            logger.info("Knowledge base is empty, processing regulatory documents")
            process_regulatory_documents(args.reg_docs, document_store, vector_store)
            kb_updated = True
        else:
            logger.info(f"Using existing knowledge base with {stats['total_clauses']} clauses")
    
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

if __name__ == "__main__":
    main()
    