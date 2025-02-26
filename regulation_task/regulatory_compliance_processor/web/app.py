# web/app.py
from flask import Flask, request, jsonify, render_template, send_from_directory, flash, redirect, url_for
import os
import logging
import tempfile
import json
from werkzeug.utils import secure_filename
import uuid

from ..document_processing.parsers import DocumentParserFactory
from ..document_processing.extractors.llm_extractor import LLMClauseExtractor
from ..knowledge_base.document_store import DocumentStore
from ..knowledge_base.vector_store import VectorStore
from ..analysis.compliance_analyzer import ComplianceAnalyzer
from ..version_control.version_tracker import VersionTracker

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("web_app.log"),
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
vector_store = VectorStore()
document_parser = DocumentParserFactory()
clause_extractor = LLMClauseExtractor()
compliance_analyzer = ComplianceAnalyzer(vector_store=vector_store)
version_tracker = VersionTracker(document_store)

# Helper function to check allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'txt'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Routes
@app.route('/')
def index():
    """Home page"""
    # Get stats for dashboard
    vector_stats = vector_store.get_stats()
    documents = document_store.get_all_documents(include_latest_version=True)
    
    return render_template(
        'index.html', 
        documents=documents,
        clause_count=vector_stats.get("total_clauses", 0)
    )

@app.route('/upload_regulatory', methods=['GET', 'POST'])
def upload_regulatory():
    """Upload regulatory document"""
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
                    # Process the document
                    doc_content = document_parser.parse_document(file_path)
                    
                    # Add to document store with version control
                    document_id, version_number = document_store.add_document(
                        file_name=filename,
                        content=doc_content["text"],
                        title=doc_content["metadata"].get("title", ""),
                        source="Regulatory Document",
                        document_type="Regulation",
                        metadata=doc_content["metadata"],
                        comment=comment
                    )
                    
                    # Extract regulatory clauses
                    # This is the part that might be failing, but we've improved the extractor
                    try:
                        logger.info(f"Starting clause extraction for {filename}")
                        clauses = clause_extractor.extract_clauses(doc_content)
                        
                        if clauses and len(clauses) > 0:
                            # Add clauses to document store
                            document_store.add_regulatory_clauses(document_id, version_number, clauses)
                            
                            # Add to vector store for semantic search
                            for clause in clauses:
                                clause["document_id"] = document_id
                                clause["document_version"] = version_number
                            
                            vector_store.add_clauses(clauses)
                            
                            flash(f'Document uploaded successfully. {len(clauses)} regulatory clauses extracted.')
                        else:
                            # Fallback if no clauses were extracted
                            logger.warning(f"No clauses extracted from {filename}, using fallback")
                            
                            # Create a simple fallback clause
                            fallback_clauses = [{
                                "id": f"{document_id}-{version_number}-fallback",
                                "section": "0",
                                "title": f"Document: {filename}",
                                "text": doc_content["text"][:2000] + "...",
                                "requirement_type": "document",
                                "source_document": filename,
                                "page_number": "1",
                                "document_id": document_id,
                                "document_version": version_number
                            }]
                            
                            # Add fallback clause
                            document_store.add_regulatory_clauses(document_id, version_number, fallback_clauses)
                            vector_store.add_clauses(fallback_clauses)
                            
                            flash(f'Document uploaded successfully. Using fallback processing.')
                    except Exception as e:
                        logger.error(f"Error extracting clauses from {filename}: {str(e)}")
                        flash(f'Document uploaded but clause extraction failed: {str(e)}')
                        # Still redirect to document details even if clause extraction failed
                    
                    return redirect(url_for('document_details', document_id=document_id))
                    
                except Exception as e:
                    logger.error(f"Error processing document {filename}: {str(e)}")
                    flash(f'Error processing document: {str(e)}')
                    return redirect(request.url)
                finally:
                    # Clean up temp file
                    if os.path.exists(file_path):
                        os.remove(file_path)
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
    """Analyze SOP compliance"""
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
                
                # Analyze compliance
                analysis_id = str(uuid.uuid4())
                compliance_results = compliance_analyzer.analyze_sop_compliance(sop_content)
                
                # Save analysis to temp file
                analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
                with open(analysis_file, 'w') as f:
                    json.dump(compliance_results, f, indent=2)
                
                return redirect(url_for('view_analysis', analysis_id=analysis_id))
                
            except Exception as e:
                logger.error(f"Error analyzing SOP {filename}: {str(e)}")
                flash(f'Error analyzing SOP: {str(e)}')
                return redirect(request.url)
            finally:
                # Clean up temp file
                if os.path.exists(file_path):
                    os.remove(file_path)
        else:
            flash(f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}')
            return redirect(request.url)
    
    return render_template('analyze_sop.html')

@app.route('/document/<int:document_id>')
def document_details(document_id):
    """View document details"""
    document = document_store.get_document(document_id)
    if not document:
        flash('Document not found')
        return redirect(url_for('index'))
    
    # Get all versions
    versions = document_store.get_document_versions(document_id)
    
    # Get clauses from the latest version
    clauses = document_store.get_regulatory_clauses(document_id)
    
    return render_template(
        'document_details.html',
        document=document,
        versions=versions,
        clauses=clauses
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
    """View compliance analysis results"""
    analysis_file = os.path.join(app.config['UPLOAD_FOLDER'], f"analysis_{analysis_id}.json")
    
    if not os.path.exists(analysis_file):
        flash('Analysis not found')
        return redirect(url_for('index'))
    
    try:
        with open(analysis_file, 'r') as f:
            analysis = json.load(f)
        
        return render_template('view_analysis.html', analysis=analysis)
        
    except Exception as e:
        logger.error(f"Error loading analysis {analysis_id}: {str(e)}")
        flash(f'Error loading analysis: {str(e)}')
        return redirect(url_for('index'))

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

@app.route('/api/document/<int:document_id>', methods=['GET'])
def api_document(document_id):
    """API endpoint to get document details"""
    document = document_store.get_document(document_id)
    if not document:
        return jsonify({"error": "Document not found"}), 404
    
    # Get all versions
    versions = document_store.get_document_versions(document_id)
    
    # Get clauses from the latest version
    clauses = document_store.get_regulatory_clauses(document_id)
    
    return jsonify({
        "document": document,
        "versions": versions,
        "clauses": clauses
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
