# web/app.py
from flask import Flask, request, jsonify, render_template, send_from_directory, flash, redirect, url_for
import os
import logging
import tempfile
import json
import threading
import time
import glob
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
    
    # Get recent analyses
    recent_analyses = []
    analysis_files = os.path.join(app.config['UPLOAD_FOLDER'], "analysis_*.json")
    for file_path in sorted(glob.glob(analysis_files), key=os.path.getmtime, reverse=True)[:5]:
        try:
            analysis_id = os.path.basename(file_path).replace("analysis_", "").replace(".json", "")
            with open(file_path, 'r') as f:
                analysis_data = json.load(f)
            
            analysis_info = {
                "id": analysis_id,
                "filename": analysis_data.get("filename", os.path.basename(file_path)),
                "status": analysis_data.get("status", "completed"),
                "timestamp": analysis_data.get("timestamp", datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat())
            }
            recent_analyses.append(analysis_info)
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
                
                # Create a placeholder result file with processing status
                processing_status = {
                    "status": "processing",
                    "filename": filename,
                    "timestamp": datetime.now().isoformat(),
                    "message": "SOP analysis in progress. This page will automatically refresh."
                }
                
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
    analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
    
    if not os.path.exists(analysis_file):
        flash('Analysis not found')
        return redirect(url_for('index'))
    
    try:
        with open(analysis_file, 'r') as f:
            analysis = json.load(f)
        
        # Check if analysis is still processing
        if isinstance(analysis, dict) and analysis.get('status') == 'processing':
            return render_template('analysis_processing.html', 
                                  analysis_id=analysis_id, 
                                  filename=analysis.get('filename', 'SOP document'),
                                  message=analysis.get('message', 'Processing in progress'))
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
