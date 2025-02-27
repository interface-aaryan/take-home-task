# web/app.py
from flask import Flask, request, jsonify, render_template, send_from_directory, flash, redirect, url_for
import os
import logging
import tempfile
import json
import threading
import time
import glob
import hashlib
import sqlite3
from werkzeug.utils import secure_filename
import uuid
from datetime import datetime

from ..document_processing.parsers import DocumentParserFactory
from ..document_processing.extractors.llm_extractor import LLMClauseExtractor
from ..document_processing.extractors.rule_extractor import RuleBasedClauseExtractor
from ..document_processing.extractors.hybrid_extractor import HybridClauseExtractor
from ..knowledge_base.document_store import DocumentStore
from ..knowledge_base.vector_store import VectorStore
from ..knowledge_base.vector_store_factory import VectorStoreFactory
from ..analysis.compliance_analyzer import ComplianceAnalyzer
from ..version_control.version_tracker import VersionTracker
from ..config import USE_RULE_BASED_EXTRACTION, USE_HYBRID_EXTRACTION, EMBEDDING_BATCH_SIZE

# Set up logging
log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "web_app.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
current_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(current_dir, 'templates')
static_dir = os.path.join(current_dir, 'static')

# Initialize Flask app
app = Flask(__name__, static_folder=static_dir, template_folder=template_dir)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB upload limit
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key_for_flash_messages')

# Initialize components
document_store = DocumentStore()
vector_store = VectorStoreFactory.create_vector_store()
document_parser = DocumentParserFactory()

# Select the appropriate extractor based on configuration
if USE_HYBRID_EXTRACTION:
    clause_extractor = HybridClauseExtractor()
elif USE_RULE_BASED_EXTRACTION:
    clause_extractor = RuleBasedClauseExtractor()
else:
    clause_extractor = LLMClauseExtractor()

compliance_analyzer = ComplianceAnalyzer(vector_store=vector_store)
version_tracker = VersionTracker(document_store)

# Dictionaries to track background processing tasks
document_processing_tasks = {}
analysis_processing_tasks = {}
removal_processing_tasks = {}

# Helper function to check allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'txt'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def analyze_sop_async(analysis_id, sop_content, filename, temp_file_path=None):
    """
    Analyze SOP compliance asynchronously in a background thread
    
    Args:
        analysis_id: ID of the analysis
        sop_content: Parsed SOP document content
        filename: Original filename
        temp_file_path: Path to temp file to clean up when done
    """
    try:
        logger.info(f"Starting background processing for SOP analysis: {filename} (ID: {analysis_id})")
        
        # Update database status to processing
        document_store.update_sop_analysis_status(analysis_id, "processing")
        
        # Analyze compliance
        compliance_results = compliance_analyzer.analyze_sop_compliance(sop_content)
        
        # Save analysis results to database
        result_json = json.dumps(compliance_results)
        document_store.add_sop_analysis(analysis_id, filename, "completed", result_json)
        
        # Also save to file for compatibility with existing code
        analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
        with open(analysis_file, 'w') as f:
            json.dump(compliance_results, f, indent=2)
            
        logger.info(f"Successfully completed SOP analysis for {filename} (ID: {analysis_id})")
        
    except Exception as e:
        logger.error(f"Error in background SOP analysis for {filename} (ID: {analysis_id}): {str(e)}")
        
        # Create error report
        error_report = {
            "error": str(e),
            "status": "failed",
            "filename": filename,
            "timestamp": datetime.now().isoformat()
        }
        
        # Update database with failed status
        result_json = json.dumps(error_report)
        document_store.add_sop_analysis(analysis_id, filename, "failed", result_json)
        
        # Save to file for compatibility
        analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
        with open(analysis_file, 'w') as f:
            json.dump(error_report, f, indent=2)
    finally:
        # Clean up temp file if provided
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"Removed temporary file: {temp_file_path}")
            except Exception as e:
                logger.error(f"Error removing temp file {temp_file_path}: {str(e)}")
        
        # Remove task from tracking dictionary
        if analysis_id in analysis_processing_tasks:
            del analysis_processing_tasks[analysis_id]

def refresh_vector_store_stats():
    """
    Force refresh the vector store stats after database operations 
    by triggering a recount of documents and clauses
    """
    try:
        # Check if we're using LangChain vector store
        if hasattr(vector_store, 'vector_store') and hasattr(vector_store.vector_store, '_collection'):
            # Force a refresh of collection metadata
            chroma_collection = vector_store.vector_store._collection
            
            # Get the latest count directly from Chroma - this is the most accurate
            # method to refresh stats after deletion
            if hasattr(chroma_collection, 'count') and callable(chroma_collection.count):
                updated_count = chroma_collection.count()
                logger.info(f"Updated vector store count: {updated_count} clauses")
                
                # Update the collection stats
                if hasattr(vector_store, '_collection_stats'):
                    vector_store._collection_stats = {"total_clauses": updated_count}
                
                return updated_count
    except Exception as e:
        logger.error(f"Error refreshing vector store stats: {str(e)}")
    
    return None

def remove_regulation_async(document_id, complete_deletion=False):
    """
    Remove a regulation asynchronously in a background thread
    
    Args:
        document_id: ID of the document to remove
        complete_deletion: Whether to completely delete the document and its history
    """
    try:
        logger.info(f"Starting background removal process for document {document_id}")
        
        # Get the document to access its filename
        document = document_store.get_document(document_id)
        if not document:
            logger.error(f"Document {document_id} not found for removal")
            document_store.update_document_status(document_id, "failed")
            return
            
        regulation_filename = document["file_name"]
        
        # Get the regulatory clauses for this document to get their IDs for vector store removal
        clauses_to_remove = document_store.get_regulatory_clauses(document_id)
        clause_ids = [str(clause["id"]) for clause in clauses_to_remove]
        
        logger.info(f"Found {len(clause_ids)} clauses to remove from vector store for document {document_id}")
        
        if complete_deletion:
            # Completely delete the document and all versions
            success, clauses_deleted = document_store.completely_delete_document(document_id)
            if not success:
                logger.error(f"Failed to completely delete document {document_id}")
                return
                
            logger.info(f"Completely deleted document {document_id} with {clauses_deleted} clauses")
        else:
            # Create a new empty version to preserve history
            with document_store.conn:
                # Get the latest version number
                cursor = document_store.conn.execute(
                    "SELECT MAX(version_number) FROM document_versions WHERE document_id = ?", 
                    (document_id,)
                )
                latest_version = cursor.fetchone()[0] or 0
                
                # Create a new version with empty content
                new_version = latest_version + 1
                timestamp = datetime.now().isoformat()
                content_hash = hashlib.sha256("".encode('utf-8')).hexdigest()
                
                # Add new empty version
                try:
                    document_store.conn.execute(
                        """
                        INSERT INTO document_versions 
                        (document_id, version_number, content_hash, content, added_date, comment) 
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, 
                        (document_id, new_version, content_hash, "", timestamp, "Removed via web interface - preserving history")
                    )
                except sqlite3.OperationalError:
                    # If column names don't match, try alternative column names
                    document_store.conn.execute(
                        """
                        INSERT INTO document_versions 
                        (document_id, version, content_hash, content, created_at, comment) 
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, 
                        (document_id, new_version, content_hash, "", timestamp, "Removed via web interface - preserving history")
                    )
                
                logger.info(f"Created new empty version {new_version} for document {document_id}")
                
                # Delete clauses for this document from the database
                cursor = document_store.conn.execute(
                    "DELETE FROM regulatory_clauses WHERE document_id = ?", 
                    (document_id,)
                )
                clauses_deleted = cursor.rowcount
                logger.info(f"Deleted {clauses_deleted} regulatory clauses for document {document_id} from database")
                
                # Update document status to completed when done
                document_store.update_document_status(document_id, "completed")
        
        # Remove just the relevant entries from the vector store (not rebuilding everything)
        if hasattr(vector_store, 'vector_store') and hasattr(vector_store.vector_store, '_collection') and clause_ids:
            # LangChain's ChromaDB implementation - targeted deletion
            try:
                chroma_collection = vector_store.vector_store._collection
                logger.info(f"Removing {len(clause_ids)} clauses from vector store")
                
                # Delete just the clauses for this document
                chroma_collection.delete(ids=clause_ids)
                
                # Persist changes
                vector_store.vector_store.persist()
                
                # Force update stats after change
                refresh_vector_store_stats()
                
                logger.info(f"Successfully removed clauses for document {document_id} from vector store")
            except Exception as e:
                logger.error(f"Error removing clauses from vector store: {str(e)}")
        
        # Log completion message
        if complete_deletion:
            logger.info(f"Successfully completely deleted regulation '{regulation_filename}' from the knowledge base")
        else:
            logger.info(f"Successfully removed regulation '{regulation_filename}' from the knowledge base")
        
    except Exception as e:
        logger.error(f"Error in background removal process for document {document_id}: {str(e)}")
        if not complete_deletion:
            document_store.update_document_status(document_id, "failed")
    finally:
        # Remove task from tracking dictionary
        if document_id in removal_processing_tasks:
            del removal_processing_tasks[document_id]

def process_document_async(document_id, doc_content, filename, temp_file_path=None):
    """
    Process a document asynchronously in a background thread
    
    Args:
        document_id: ID of the document to process
        doc_content: Parsed document content
        filename: Original filename
        temp_file_path: Path to temp file to clean up when done
    """
    try:
        logger.info(f"Starting background processing for document {document_id} ({filename})")
        
        # Extract regulatory clauses
        logger.info(f"Extracting clauses from {filename}")
        clauses = clause_extractor.extract_clauses(doc_content)
        
        if clauses and len(clauses) > 0:
            # Get the current version number for this document
            cursor = document_store.conn.execute(
                "SELECT MAX(version_number) FROM document_versions WHERE document_id = ?", 
                (document_id,)
            )
            version_number = cursor.fetchone()[0] or 1
            
            # Add clauses to document store
            logger.info(f"Adding {len(clauses)} clauses to document store for document {document_id}")
            document_store.add_regulatory_clauses(document_id, version_number, clauses)
            
            # Add clauses to vector store in batches
            logger.info(f"Adding clauses to vector store in batches")
            for i in range(0, len(clauses), EMBEDDING_BATCH_SIZE):
                batch_clauses = clauses[i:i+EMBEDDING_BATCH_SIZE]
                
                # Add document_id and version to each clause
                for clause in batch_clauses:
                    clause["document_id"] = document_id
                    clause["document_version"] = version_number
                
                # Add to vector store
                vector_store.add_clauses(batch_clauses)
                logger.info(f"Added batch {i//EMBEDDING_BATCH_SIZE + 1}/{(len(clauses) + EMBEDDING_BATCH_SIZE - 1)//EMBEDDING_BATCH_SIZE} of clauses to vector store")
            
            logger.info(f"Successfully processed document {document_id} with {len(clauses)} clauses")
            document_store.update_document_status(document_id, "completed")
        else:
            # Fallback if no clauses were extracted
            logger.warning(f"No clauses extracted from {filename}, using fallback")
            
            # Create a simple fallback clause
            fallback_clauses = [{
                "id": f"{document_id}-fallback",
                "section": "0",
                "title": f"Document: {filename}",
                "text": doc_content["text"][:2000] + "...",
                "requirement_type": "document",
                "source_document": filename,
                "page_number": "1",
                "document_id": document_id,
                "document_version": 1
            }]
            
            # Add fallback clause
            document_store.add_regulatory_clauses(document_id, 1, fallback_clauses)
            vector_store.add_clauses(fallback_clauses)
            document_store.update_document_status(document_id, "completed")
            logger.info(f"Added fallback clause for document {document_id}")
            
    except Exception as e:
        logger.error(f"Error in background processing for document {document_id}: {str(e)}")
        document_store.update_document_status(document_id, "failed")
    finally:
        # Clean up temp file if provided
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"Removed temporary file: {temp_file_path}")
            except Exception as e:
                logger.error(f"Error removing temp file {temp_file_path}: {str(e)}")
        
        # Remove task from tracking dictionary
        if document_id in document_processing_tasks:
            del document_processing_tasks[document_id]

# Routes
@app.route('/')
def index():
    """Home page with recent analyses"""
    # Get stats for dashboard
    vector_stats = vector_store.get_stats()
    documents = document_store.get_all_documents(include_latest_version=True)
    
    # Get recent analyses from database
    db_analyses = document_store.get_all_sop_analyses(limit=5)
    
    # Convert to the format expected by the template
    recent_analyses = []
    for analysis in db_analyses:
        recent_analyses.append({
            "id": analysis["id"],
            "filename": analysis["filename"],
            "status": analysis["status"],
            "timestamp": analysis["updated_at"]
        })
    
    # If we have fewer than 5 analyses from database, supplement with file-based ones
    if len(recent_analyses) < 5:
        analysis_files = os.path.join(app.config['UPLOAD_FOLDER'], "analysis_*.json")
        for file_path in sorted(glob.glob(analysis_files), key=os.path.getmtime, reverse=True):
            # Skip if we already have this analysis
            analysis_id = os.path.basename(file_path).replace("analysis_", "").replace(".json", "")
            if any(a["id"] == analysis_id for a in recent_analyses):
                continue
                
            try:
                with open(file_path, 'r') as f:
                    analysis_data = json.load(f)
                
                analysis_info = {
                    "id": analysis_id,
                    "filename": analysis_data.get("filename", os.path.basename(file_path)),
                    "status": analysis_data.get("status", "completed"),
                    "timestamp": analysis_data.get("timestamp", datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat())
                }
                recent_analyses.append(analysis_info)
                
                # Stop if we have 5 analyses
                if len(recent_analyses) >= 5:
                    break
            except Exception as e:
                logger.error(f"Error loading analysis file {file_path}: {str(e)}")
    
    return render_template(
        'index.html', 
        documents=documents,
        clause_count=vector_stats.get("total_clauses", 0),
        recent_analyses=recent_analyses
    )

@app.route('/upload_regulatory', methods=['GET', 'POST'])
def upload_regulatory():
    """Upload regulatory document with async processing"""
    if request.method == 'POST':
        try:
            # Check if file part exists
            if 'file' not in request.files:
                flash('No file part')
                return redirect(request.url)
                
            file = request.files['file']
            
            # Check if file is selected
            if file.filename == '':
                flash('No file selected')
                return redirect(request.url)
                
            # Check if file is allowed
            if file and allowed_file(file.filename):
                # Save file to temp location
                filename = secure_filename(file.filename)
                comment = request.form.get('comment', 'Uploaded via web interface')
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                
                try:
                    # Parse the document content
                    doc_content = document_parser.parse_document(file_path)
                    
                    # Add to document store with status "processing"
                    document_id, version_number = document_store.add_document(
                        file_name=filename,
                        content=doc_content["text"],
                        title=doc_content["metadata"].get("title", ""),
                        source="Regulatory Document",
                        document_type="Regulation",
                        metadata=doc_content["metadata"],
                        comment=comment,
                        status="processing"
                    )
                    
                    # Start background processing
                    logger.info(f"Starting background processing thread for document {document_id}")
                    process_thread = threading.Thread(
                        target=process_document_async, 
                        args=(document_id, doc_content, filename, file_path)
                    )
                    process_thread.daemon = True
                    process_thread.start()
                    
                    # Store thread in tracking dictionary
                    document_processing_tasks[document_id] = process_thread
                    
                    flash(f'Document uploaded successfully and is being processed in the background. You can view the document details page for status updates.')
                    return redirect(url_for('document_details', document_id=document_id))
                    
                except Exception as e:
                    logger.error(f"Error processing document {filename}: {str(e)}")
                    flash(f'Error processing document: {str(e)}')
                    
                    # Clean up temp file on error
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    
                    return redirect(request.url)
            else:
                flash(f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}')
                return redirect(request.url)
        except Exception as e:
            logger.error(f"Unexpected error in upload_regulatory: {str(e)}")
            flash(f'Unexpected error: {str(e)}')
            return redirect(request.url)
    
    return render_template('upload_regulatory.html')

@app.route('/analyze_sop', methods=['GET', 'POST'])
def analyze_sop():
    """Analyze SOP compliance with async processing"""
    if request.method == 'POST':
        # Check if any regulation is being removed
        if removal_processing_tasks:
            flash('A regulation is currently being removed from the knowledge base. Please try again when the process is complete.')
            return redirect(request.url)
            
        # Check if file part exists
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
            
        file = request.files['file']
        
        # Check if file is selected
        if file.filename == '':
            flash('No file selected')
            return redirect(request.url)
            
        # Check if file is allowed
        if file and allowed_file(file.filename):
            # Save file to temp location
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            try:
                # Process the SOP
                sop_content = document_parser.parse_document(file_path)
                
                # Generate unique analysis ID
                analysis_id = str(uuid.uuid4())
                
                # Create a placeholder in the database
                current_time = datetime.now().isoformat()
                processing_status = {
                    "status": "processing",
                    "filename": filename,
                    "timestamp": current_time,
                    "message": "SOP analysis in progress. This page will automatically refresh."
                }
                
                # Add record to database with processing status
                document_store.add_sop_analysis(
                    analysis_id, 
                    filename, 
                    "processing", 
                    json.dumps(processing_status)
                )
                
                # Also create file for compatibility
                analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
                with open(analysis_file, 'w') as f:
                    json.dump(processing_status, f, indent=2)
                
                # Start background analysis
                logger.info(f"Starting background analysis thread for SOP: {filename}")
                analysis_thread = threading.Thread(
                    target=analyze_sop_async,
                    args=(analysis_id, sop_content, filename, file_path)
                )
                analysis_thread.daemon = True
                analysis_thread.start()
                
                # Store thread in tracking dictionary
                analysis_processing_tasks[analysis_id] = analysis_thread
                
                flash(f'SOP document uploaded and analysis started. You will be notified when it completes.')
                return redirect(url_for('view_analysis', analysis_id=analysis_id))
                
            except Exception as e:
                logger.error(f"Error analyzing SOP {filename}: {str(e)}")
                flash(f'Error analyzing SOP: {str(e)}')
                
                # Clean up temp file on error
                if os.path.exists(file_path):
                    os.remove(file_path)
                    
                return redirect(request.url)
        else:
            flash(f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}')
            return redirect(request.url)
    
    # Add warning if regulation removal is in progress
    if removal_processing_tasks:
        flash('A regulation is currently being removed from the knowledge base. Analysis functionality is temporarily unavailable.', 'warning')
        
    return render_template('analyze_sop.html')

@app.route('/document/<int:document_id>')
def document_details(document_id):
    """View document details with processing status"""
    document = document_store.get_document(document_id)
    if not document:
        flash('Document not found')
        return redirect(url_for('index'))
    
    # Get all versions
    versions = document_store.get_document_versions(document_id)
    
    # Get document status, handling the case where status might not be in the document dictionary
    if hasattr(document, 'get'):
        status = document.get('status', 'completed')
    else:
        status = document_store.get_document_status(document_id) or "completed"
    
    # Get clauses from the latest version (if processing is complete)
    clauses = []
    if status == "completed":
        clauses = document_store.get_regulatory_clauses(document_id)
    
    # Add status to document dictionary if it doesn't exist
    if hasattr(document, 'get') and 'status' not in document:
        document['status'] = status
    
    return render_template(
        'document_details.html',
        document=document,
        versions=versions,
        clauses=clauses,
        status=status
    )

@app.route('/document/<int:document_id>/version/<int:version_number>')
def document_version(document_id, version_number):
    """View specific document version"""
    document = document_store.get_document(document_id, version_number)
    if not document:
        flash('Document version not found')
        return redirect(url_for('document_details', document_id=document_id))
    
    # Get clauses for this version
    clauses = document_store.get_regulatory_clauses(document_id, version_number)
    
    # Get comparison with previous version if not the first version
    comparison = None
    if version_number > 1:
        comparison = version_tracker.compare_with_previous_version(document_id, version_number)
    
    return render_template(
        'document_version.html',
        document=document,
        clauses=clauses,
        comparison=comparison
    )

@app.route('/view_analysis/<analysis_id>')
def view_analysis(analysis_id):
    """View compliance analysis results with status handling"""
    # First try to get from database
    analysis_record = document_store.get_sop_analysis(analysis_id)
    
    if analysis_record:
        # Get status from database record
        status = analysis_record.get('status')
        
        if status == 'processing':
            # Analysis is still processing
            try:
                analysis_data = json.loads(analysis_record.get('result_json', '{}'))
                # Check if task is actually in progress (still in our tracking dict)
                in_progress = analysis_id in analysis_processing_tasks
                return render_template('analysis_processing.html', 
                                      analysis_id=analysis_id, 
                                      filename=analysis_record.get('filename', 'SOP document'),
                                      message=analysis_data.get('message', 'Processing in progress'),
                                      in_progress=in_progress)  # Flag to show stop button
            except:
                # If we can't parse the JSON, just show generic processing
                # Check if task is actually in progress (still in our tracking dict)
                in_progress = analysis_id in analysis_processing_tasks
                return render_template('analysis_processing.html', 
                                      analysis_id=analysis_id, 
                                      filename=analysis_record.get('filename', 'SOP document'),
                                      message='Processing in progress',
                                      in_progress=in_progress)  # Flag to show stop button
        
        elif status == 'cancelled':
            # Analysis was cancelled by user
            try:
                analysis_data = json.loads(analysis_record.get('result_json', '{}'))
                return render_template('analysis_failed.html',
                                      analysis_id=analysis_id,
                                      filename=analysis_record.get('filename', 'SOP document'),
                                      error=analysis_data.get('error', 'Analysis was cancelled by user'))
            except:
                # If we can't parse the JSON, show generic cancellation message
                return render_template('analysis_failed.html',
                                      analysis_id=analysis_id,
                                      filename=analysis_record.get('filename', 'SOP document'),
                                      error='Analysis was cancelled by user')
        
        elif status == 'failed':
            # Analysis failed
            try:
                analysis_data = json.loads(analysis_record.get('result_json', '{}'))
                return render_template('analysis_failed.html',
                                      analysis_id=analysis_id,
                                      filename=analysis_record.get('filename', 'SOP document'),
                                      error=analysis_data.get('error', 'Unknown error'))
            except:
                # If we can't parse the JSON, show generic error
                return render_template('analysis_failed.html',
                                      analysis_id=analysis_id,
                                      filename=analysis_record.get('filename', 'SOP document'),
                                      error='Unknown error occurred during analysis')
        
        else:
            # Analysis completed successfully
            try:
                analysis_data = json.loads(analysis_record.get('result_json', '{}'))
                return render_template('view_analysis.html', analysis=analysis_data)
            except Exception as e:
                logger.error(f"Error parsing analysis JSON {analysis_id}: {str(e)}")
                flash(f'Error loading analysis results: {str(e)}')
                return redirect(url_for('index'))
    
    # Fall back to file-based approach if not in database
    analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
    
    if not os.path.exists(analysis_file):
        flash('Analysis not found')
        return redirect(url_for('index'))
    
    try:
        with open(analysis_file, 'r') as f:
            analysis = json.load(f)
        
        # Check if analysis is still processing
        if isinstance(analysis, dict) and analysis.get('status') == 'processing':
            # Check if task is in progress (still in our tracking dict)
            in_progress = analysis_id in analysis_processing_tasks
            return render_template('analysis_processing.html', 
                                  analysis_id=analysis_id, 
                                  filename=analysis.get('filename', 'SOP document'),
                                  message=analysis.get('message', 'Processing in progress'),
                                  in_progress=in_progress)  # Flag to show stop button
        # Check if analysis was cancelled
        elif isinstance(analysis, dict) and analysis.get('status') == 'cancelled':
            return render_template('analysis_failed.html',
                                  analysis_id=analysis_id,
                                  filename=analysis.get('filename', 'SOP document'),
                                  error=analysis.get('error', 'Analysis was cancelled by user'))
        # Check if analysis failed
        elif isinstance(analysis, dict) and analysis.get('status') == 'failed':
            return render_template('analysis_failed.html',
                                  analysis_id=analysis_id,
                                  filename=analysis.get('filename', 'SOP document'),
                                  error=analysis.get('error', 'Unknown error'))
        # Analysis completed successfully
        else:
            return render_template('view_analysis.html', analysis=analysis)
        
    except Exception as e:
        logger.error(f"Error loading analysis {analysis_id}: {str(e)}")
        flash(f'Error loading analysis: {str(e)}')
        return redirect(url_for('index'))

@app.route('/all_documents')
def all_documents():
    """View all regulatory documents"""
    documents = document_store.get_all_documents(include_latest_version=True)
    
    return render_template(
        'all_documents.html',
        documents=documents
    )
    
@app.route('/all_analyses')
def all_analyses():
    """View all SOP analyses"""
    # Get all analyses from database
    db_analyses = document_store.get_all_sop_analyses()
    
    # Convert to the format expected by the template
    analyses = []
    for analysis in db_analyses:
        analyses.append({
            "id": analysis["id"],
            "filename": analysis["filename"],
            "status": analysis["status"],
            "created_at": analysis["created_at"],
            "updated_at": analysis["updated_at"]
        })
    
    # Supplement with file-based analyses that might not be in the database
    analysis_files = os.path.join(app.config['UPLOAD_FOLDER'], "analysis_*.json")
    for file_path in glob.glob(analysis_files):
        analysis_id = os.path.basename(file_path).replace("analysis_", "").replace(".json", "")
        
        # Skip if we already have this analysis
        if any(a["id"] == analysis_id for a in analyses):
            continue
            
        try:
            with open(file_path, 'r') as f:
                analysis_data = json.load(f)
            
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()
            analyses.append({
                "id": analysis_id,
                "filename": analysis_data.get("filename", os.path.basename(file_path)),
                "status": analysis_data.get("status", "completed"),
                "created_at": analysis_data.get("timestamp", file_mtime),
                "updated_at": file_mtime
            })
        except Exception as e:
            logger.error(f"Error loading analysis file {file_path}: {str(e)}")
    
    # Sort by updated_at
    analyses.sort(key=lambda x: x["updated_at"], reverse=True)
    
    return render_template(
        'all_analyses.html',
        analyses=analyses
    )

@app.route('/search', methods=['GET', 'POST'])
def search():
    """Search regulatory clauses"""
    if request.method == 'POST':
        query = request.form.get('query', '')
        if not query:
            flash('Please enter a search query')
            return redirect(request.url)
        
        # Search using vector store
        results = vector_store.search(query, k=20)
        
        return render_template('search_results.html', query=query, results=results)
    
    return render_template('search.html')

@app.route('/download_report/<analysis_id>')
def download_report(analysis_id):
    """Download analysis report"""
    analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
    
    if not os.path.exists(analysis_file):
        flash('Analysis report not found')
        return redirect(url_for('index'))
    
    return send_from_directory(
        directory=app.config['UPLOAD_FOLDER'],
        path=f"analysis_{analysis_id}.json",
        as_attachment=True,
        download_name="compliance_analysis_report.json"
    )
    
@app.route('/stop_analysis/<analysis_id>', methods=['POST'])
def stop_analysis(analysis_id):
    """Stop a running analysis task"""
    # Check if the analysis is in our tracking dictionary
    if analysis_id in analysis_processing_tasks:
        logger.info(f"User requested to stop analysis {analysis_id}")
        
        # We can't directly stop a thread in Python, but we can mark it as cancelled
        # in the database so it won't be shown as "processing" anymore
        error_report = {
            "error": "Analysis cancelled by user",
            "status": "cancelled",
            "timestamp": datetime.now().isoformat()
        }
        
        # Update database status
        document_store.add_sop_analysis(analysis_id, 
            document_store.get_sop_analysis(analysis_id).get('filename', 'Unknown'), 
            "cancelled", 
            json.dumps(error_report)
        )
        
        # Remove from tracking dictionary
        del analysis_processing_tasks[analysis_id]
        
        flash('Analysis has been stopped.')
        return redirect(url_for('all_analyses'))
    else:
        flash('Analysis is not currently running or could not be stopped.')
        return redirect(url_for('view_analysis', analysis_id=analysis_id))
        
@app.route('/remove_analysis/<analysis_id>', methods=['POST'])
def remove_analysis(analysis_id):
    """Remove an analysis from the system"""
    # Check if the analysis exists
    analysis_record = document_store.get_sop_analysis(analysis_id)
    analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
    
    # Stop it first if it's running
    if analysis_id in analysis_processing_tasks:
        # Mark as cancelled
        error_report = {
            "error": "Analysis cancelled and removed by user",
            "status": "cancelled",
            "timestamp": datetime.now().isoformat()
        }
        document_store.add_sop_analysis(analysis_id, 
            analysis_record.get('filename', 'Unknown'), 
            "cancelled", 
            json.dumps(error_report)
        )
        # Remove from tracking
        del analysis_processing_tasks[analysis_id]
    
    # Now delete from database and file system
    try:
        # Delete from database if it exists
        if analysis_record:
            with document_store.conn:
                document_store.conn.execute("DELETE FROM sop_analyses WHERE id = ?", (analysis_id,))
                logger.info(f"Deleted analysis {analysis_id} from database")
        
        # Delete file if it exists
        if os.path.exists(analysis_file):
            os.remove(analysis_file)
            logger.info(f"Deleted analysis file for {analysis_id}")
            
        flash('Analysis has been removed from the system.')
    except Exception as e:
        logger.error(f"Error removing analysis {analysis_id}: {str(e)}")
        flash(f'Error removing analysis: {str(e)}')
        
    return redirect(url_for('all_analyses'))

@app.route('/api/documents', methods=['GET'])
def api_documents():
    """API endpoint to get all documents"""
    documents = document_store.get_all_documents(include_latest_version=True)
    return jsonify(documents)

@app.route('/api/document_status/<int:document_id>', methods=['GET'])
def api_document_status(document_id):
    """API endpoint to check document processing status"""
    status = document_store.get_document_status(document_id)
    if not status:
        return jsonify({"error": "Document not found"}), 404
        
    return jsonify({"document_id": document_id, "status": status})

@app.route('/api/document/<int:document_id>', methods=['GET'])
def api_document(document_id):
    """API endpoint to get document details"""
    document = document_store.get_document(document_id)
    if not document:
        return jsonify({"error": "Document not found"}), 404
    
    # Get all versions
    versions = document_store.get_document_versions(document_id)
    
    # Get document status
    status = document_store.get_document_status(document_id) or "unknown"
    
    # Get clauses from the latest version
    clauses = []
    if status == "completed":
        clauses = document_store.get_regulatory_clauses(document_id)
    
    return jsonify({
        "document": document,
        "versions": versions,
        "clauses": clauses,
        "status": status
    })

@app.route('/remove_regulation/<int:document_id>', methods=['POST'])
def remove_regulation(document_id):
    """Remove a regulation from the knowledge base"""
    # Get the document to check if it exists and for display
    document = document_store.get_document(document_id)
    if not document:
        flash('Document not found')
        return redirect(url_for('index'))
    
    # Check if any removal tasks are already running
    if removal_processing_tasks:
        flash('Another regulation is currently being removed. Please try again later when the vector store rebuild is complete.')
        return redirect(url_for('document_details', document_id=document_id))
    
    # Also check for any document processing tasks
    if document_processing_tasks:
        flash('Documents are currently being processed. Please try again later when all processing is complete.')
        return redirect(url_for('document_details', document_id=document_id))
    
    # Check for complete deletion mode
    complete_deletion = request.form.get('complete_deletion') == 'true'
    
    if not complete_deletion:
        # Set document status to removing
        document_store.update_document_status(document_id, "removing")
    
    # Start background removal process
    logger.info(f"Starting background {'complete deletion' if complete_deletion else 'removal'} process for document {document_id}")
    removal_thread = threading.Thread(
        target=remove_regulation_async,
        args=(document_id, complete_deletion)
    )
    removal_thread.daemon = True
    removal_thread.start()
    
    # Store thread in tracking dictionary
    removal_processing_tasks[document_id] = removal_thread
    
    # Show a message
    if complete_deletion:
        flash(f'Regulation complete deletion process started. The regulation and all its history will be removed from the system.')
        return redirect(url_for('all_documents'))
    else:
        flash(f'Regulation removal process started. The regulation will be removed from both the database and vector store.')
        return redirect(url_for('document_details', document_id=document_id))
        
@app.route('/delete_regulation/<int:document_id>', methods=['POST'])
def delete_regulation(document_id):
    """Completely delete a regulation including its history"""
    # This is a shortcut route that sets the complete_deletion flag to true
    return remove_regulation(document_id)

@app.route('/api/search', methods=['GET'])
def api_search():
    """API endpoint for search"""
    query = request.args.get('query', '')
    if not query:
        return jsonify({"error": "Missing query parameter"}), 400
    
    limit = request.args.get('limit', 20)
    try:
        limit = int(limit)
    except ValueError:
        limit = 20
    
    results = vector_store.search(query, k=limit)
    return jsonify(results)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

@app.route('/test')
def test():
    return """
    <html>
        <body>
            <h1>Test Page</h1>
            <p>If you can see this, Flask is working!</p>
        </body>
    </html>
    """

def run_app(host='0.0.0.0', port=5052, debug=False):
    """Run the Flask application"""
    app.run(host=host, port=port, debug=debug)

if __name__ == '__main__':
    run_app(debug=True)
