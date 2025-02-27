# Regulatory Compliance Document Processor

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Project Structure](#2-project-structure)
3. [Database Structure](#3-database-structure)
4. [API Endpoints](#4-api-endpoints)
5. [Document Processing Flow](#5-document-processing-flow)
6. [Version Control System](#6-version-control-system)
7. [Installation and Setup](#7-installation-and-setup)
8. [Usage Examples](#8-usage-examples)
9. [General Project Workflow](#9-general-project-workflow)

## 1. Project Overview

### Purpose
The Regulatory Compliance Document Processor is a sophisticated tool designed to analyze Standard Operating Procedure (SOP) documents against regulatory requirements. It identifies potential compliance issues and provides recommendations for improvements.

### Main Functionalities
- Extraction of regulatory clauses from multiple regulation documents
- Semantic search for relevant regulatory clauses applicable to SOPs
- Deep compliance analysis of SOPs against regulatory requirements
- Prioritized recommendations for SOP improvements
- Version control for regulatory documents
- Web interface for document management and analysis

### Technologies Used
- **Python** - Core programming language
- **OpenAI API** - LLM-based extraction and analysis
- **LangChain** - Vector store integration and document operations
- **ChromaDB** - Vector database for semantic search
- **FAISS** - Alternative vector indexing (optional)
- **Flask** - Web application framework
- **PyMuPDF & PyPDF2** - PDF document parsing
- **SQLite** - Document and analysis storage

## 2. Project Structure

### Main Directories
- `/regulatory_compliance_processor/` - Core application code
  - `/analysis/` - Compliance analysis logic
  - `/document_processing/` - Document parsing and clause extraction
  - `/knowledge_base/` - Vector store and document storage
  - `/version_control/` - Document versioning system
  - `/web/` - Flask web application
  - `/api/` - API interfaces
  - `/cache/` - Caching for embeddings and documents
  - `/data/` - Data storage for document and vector databases
  - `/logs/` - Application logs
- `/data/` - Input regulation documents and SOPs
- `/reports/` - Generated compliance reports
- `/scripts/` - Utility scripts for database management

### Key Files
- `main.py` - Main application entry point
- `config.py` - Application configuration
- `regulatory_compliance_processor/web/app.py` - Flask web application
- `regulatory_compliance_processor/analysis/compliance_analyzer.py` - SOP compliance analysis
- `regulatory_compliance_processor/knowledge_base/vector_store_factory.py` - Vector database factory
- `regulatory_compliance_processor/document_processing/parsers/pdf_parser.py` - PDF document parsing
- `regulatory_compliance_processor/document_processing/extractors/hybrid_extractor.py` - Regulatory clause extraction

### Organization
The project follows a modular architecture with clear separation of concerns:
- Document processing pipeline (parsing → extraction)
- Vector database for semantic search
- Analysis engine for compliance checking
- Web interface for user interaction
- Version control system for document management

## 3. Database Structure

### Database Types
- **SQLite** - Document storage and metadata (`document_db`)
- **ChromaDB/FAISS** - Vector database for semantic search (`vector_db`)

### Schema Details

#### SQLite Database Schema

**documents table**
```
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    filename TEXT,
    content_hash TEXT,
    file_type TEXT,
    created_at TIMESTAMP,
    status TEXT,
    processing_info TEXT
)
```

**document_versions table**
```
CREATE TABLE document_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    version_number INTEGER,
    content TEXT,
    content_hash TEXT,
    created_at TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (document_id) REFERENCES documents(id)
)
```

**regulatory_clauses table**
```
CREATE TABLE regulatory_clauses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    document_version_id INTEGER,
    clause_id TEXT,
    section TEXT,
    content TEXT,
    metadata TEXT,
    embedding_id TEXT,
    FOREIGN KEY (document_id) REFERENCES documents(id),
    FOREIGN KEY (document_version_id) REFERENCES document_versions(id)
)
```

**sop_analyses table**
```
CREATE TABLE sop_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sop_title TEXT,
    sop_filename TEXT,
    sop_content_hash TEXT,
    created_at TIMESTAMP,
    status TEXT,
    report_path TEXT,
    metadata TEXT
)
```

### Data Storage
- Document content and metadata stored in SQLite
- Document embeddings stored in ChromaDB/FAISS
- Regulatory clauses stored in both SQLite and vector database
- Analysis results stored in SQLite and JSON files

## 4. API Endpoints

### Web Endpoints

| Endpoint | Method | Description | Parameters | Response |
|----------|--------|-------------|------------|----------|
| `/` | GET | Home/dashboard page | None | HTML dashboard with system stats |
| `/upload_regulatory` | POST | Upload regulatory documents | `file` (multipart) | Redirect to document page |
| `/analyze_sop` | POST | Upload and analyze SOP | `file` (multipart) | Redirect to analysis page |
| `/document/<document_id>` | GET | View document details | `document_id` (path) | HTML document detail page |
| `/document/<document_id>/version/<version_number>` | GET | View specific document version | `document_id`, `version_number` (path) | HTML document version page |
| `/view_analysis/<analysis_id>` | GET | View analysis results | `analysis_id` (path) | HTML analysis report page |
| `/all_documents` | GET | List all regulatory documents | None | HTML documents list page |
| `/all_analyses` | GET | List all SOP analyses | None | HTML analyses list page |
| `/search` | GET | Search regulatory clauses | `q` (query) | HTML search results page |
| `/remove_regulation/<int:document_id>` | POST | Remove a regulation | `document_id` (path) | Redirect to documents page |

### JSON API Endpoints

| Endpoint | Method | Description | Parameters | Response Format |
|----------|--------|-------------|------------|-----------------|
| `/api/documents` | GET | Get all documents | None | JSON array of documents |
| `/api/document/<document_id>` | GET | Get document details | `document_id` (path) | JSON document object |
| `/api/document_status/<document_id>` | GET | Check document processing status | `document_id` (path) | JSON status object |
| `/api/search` | GET | Search regulatory clauses | `q` (query), `limit` (optional) | JSON array of clauses |
| `/api/analyze_sop` | POST | Analyze SOP document | `file` (multipart) | JSON analysis result |

#### Sample Response - Document Detail

```json
{
  "id": 5,
  "title": "API 510 2022",
  "filename": "REG-API_510_2022.pdf",
  "created_at": "2025-02-26T15:32:10",
  "status": "processed",
  "file_type": "pdf",
  "versions": [
    {
      "version_number": 1,
      "created_at": "2025-02-26T15:32:10",
      "clauses_count": 253
    }
  ],
  "current_version": 1
}
```

#### Sample Response - Search Results

```json
{
  "results": [
    {
      "id": 128,
      "document_id": 5,
      "document_title": "API 510 2022",
      "section": "6.4.2",
      "content": "Inspectors shall have sufficient training and experience to interpret and evaluate results in terms of applicable codes and standards.",
      "score": 0.89
    },
    ...
  ],
  "count": 12,
  "query": "inspector training requirements"
}
```

## 5. Document Processing Flow

### Regulation Processing
1. Document parsing using optimized parsers for different file types
2. Clause extraction using hybrid approach:
   - Rule-based extraction for straightforward clauses
   - LLM-based extraction for complex sections
3. Storage in document database with versioning
4. Embedding generation and storage in vector database

### SOP Analysis
1. SOP document parsing
2. Section extraction using LLM
3. Semantic search for relevant regulatory clauses
4. Compliance analysis against applicable regulations
5. Generation of recommendations with priority levels
6. Summary report creation

### Caching
- Embedding cache to reduce API calls
- Document processing cache for extracted clauses
- Analysis cache for completed analyses

## 6. Version Control System

### Version Tracking
- Each document has multiple versions tracked
- Full version history maintained in database
- Content hash to identify changes

### Version Comparison
- Diff engine to compare document versions
- Identification of added, removed, and modified clauses
- Change summaries for document history

#### Version Comparison Example:
```python
# Using the VersionTracker to compare document versions
version_tracker = VersionTracker()
diff_result = version_tracker.compare_with_previous_version(document_id, current_version)

# Diff result contains:
# - added_clauses: new clauses in current version
# - removed_clauses: clauses removed from previous version
# - modified_clauses: clauses changed between versions
# - change_summary: textual summary of changes
```

## 7. Installation and Setup

### Dependencies
- Python 3.8+
- OpenAI API key (environment variable `OPENAI_API_KEY`)
- PyMuPDF, PyPDF2 for document parsing
- LangChain and ChromaDB for vector storage
- Flask for web interface

### Installing with uv

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver. To set up this project with uv:

1. Install uv:
```bash
pip install uv
```

2. Clone the repository and navigate to the project directory.

3. Sync dependencies from pyproject.toml:
```bash
uv sync
```

This will install all project dependencies from pyproject.toml in a virtual environment.

### Environment Configuration
- Configuration via `config.py`
- Adjustable settings for embedding models, batch sizes, processing options
- Feature toggles for optimizations

```python
# Sample configuration
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-ada-002"
COMPLETION_MODEL = "gpt-3.5-turbo"
VECTOR_STORE_TYPE = "chroma"  # Options: "chroma", "faiss"
BATCH_SIZE = 10
CACHE_EMBEDDINGS = True
```

### Database Setup
- Automatic creation of SQLite database
- Vector database initialization via VectorStoreFactory

```python
# Database initialization happens automatically when the app starts
# To manually initialize:
from regulatory_compliance_processor.knowledge_base.document_store import DocumentStore
from regulatory_compliance_processor.knowledge_base.vector_store_factory import VectorStoreFactory

document_store = DocumentStore()
vector_store = VectorStoreFactory.create_vector_store()
```

## 8. Usage Examples

### Running the Application
```bash
# Run main application
uv run regulation_task/main.py

# Run web app
uv run -m regulatory_compliance_processor.web.app
```

### Command Line Options
```bash
# Rebuild knowledge base from scratch
python main.py --rebuild-kb

# Process specific SOP file
python main.py --sop /path/to/sop.docx

# Only build knowledge base without processing SOP
python main.py --build-only
```

### Using the Scripts
```bash
# Add a new regulation
python scripts/add_regulation.py --file /path/to/regulation.pdf

# List all regulations
python scripts/list_regulations.py

# Remove a regulation
python scripts/remove_regulation.py --document_id 5

# Rebuild the vector store
python scripts/rebuild_vector_store.py
```

### Web Interface
- Upload regulatory documents via web interface
- Analyze SOPs and view compliance reports
- Search regulatory clauses by keyword/content
- View document version history

## 9. General Project Workflow

### High-Level Data Flow
```
[Regulation Documents] → [Document Parser] → [Clause Extractor] → [Document Database]
                                                                → [Vector Database]
                                                                
[SOP Document] → [SOP Parser] → [Compliance Analyzer] ← [Relevant Clauses] ← [Vector Search]
                              → [Compliance Report]
```

### Component Interaction
- **DocumentParserFactory** creates appropriate parsers based on file type
- **Document extractors** identify and extract regulatory clauses
- **Vector store** enables semantic search for relevant clauses
- **Compliance analyzer** evaluates SOP compliance against regulations
- **Web interface** provides user access to all functionality

The system employs optimizations for memory management, parallel processing, and caching to handle large documents and datasets efficiently. The modular architecture allows for easy extension and maintenance of individual components without affecting the entire system.

When a new regulation is added:
1. It's parsed and clauses are extracted
2. Embeddings are generated for each clause
3. Clauses are stored in the document database
4. Embeddings are stored in the vector database
5. Version tracking information is recorded

When an SOP is analyzed:
1. The SOP is parsed into sections
2. Relevant regulatory clauses are retrieved via semantic search
3. The compliance analyzer evaluates each section against applicable regulations
4. A prioritized list of recommendations is generated
5. A comprehensive report is created and stored

All these operations are accessible through both the command line interface and the web application, allowing for flexible usage depending on the user's needs.