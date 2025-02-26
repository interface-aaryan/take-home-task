# knowledge_base/document_store.py
import threading
import sqlite3
import json
import logging
import os
import hashlib
from datetime import datetime
from pathlib import Path


from ..config import DOCUMENT_DB_PATH

logger = logging.getLogger(__name__)

class DocumentStore:
    """Store for regulatory documents with version control"""
    
    
    def __init__(self, db_path=DOCUMENT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = self._init_db()

    
    
    def _init_db(self):
        """Initialize the SQLite database"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        
        # Create tables if they don't exist
        with conn:
            # Documents table
            conn.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                title TEXT,
                source TEXT,
                document_type TEXT,
                added_date TEXT NOT NULL,
                last_updated TEXT NOT NULL,
                metadata TEXT
            )
            ''')
            
            # Document versions table
            conn.execute('''
            CREATE TABLE IF NOT EXISTS document_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                content TEXT NOT NULL,
                added_date TEXT NOT NULL,
                comment TEXT,
                FOREIGN KEY (document_id) REFERENCES documents (id),
                UNIQUE (document_id, version_number)
            )
            ''')
            
            # Regulatory clauses table
            conn.execute('''
            CREATE TABLE IF NOT EXISTS regulatory_clauses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                document_version INTEGER NOT NULL,
                clause_id TEXT,
                section TEXT,
                title TEXT,
                text TEXT NOT NULL,
                requirement_type TEXT,
                page_number TEXT,
                metadata TEXT,
                FOREIGN KEY (document_id) REFERENCES documents (id),
                FOREIGN KEY (document_id, document_version) REFERENCES document_versions (document_id, version_number)
            )
            ''')
        
        return conn
    
    def add_document(self, file_name, content, title=None, source=None, document_type=None, metadata=None, comment=None):
        """
        Add a new document or a new version of an existing document
        
        Returns:
            Tuple (document_id, version_number)
        """
        try:
            # Check if document already exists
            with self.conn:
                cursor = self.conn.execute(
                    "SELECT id FROM documents WHERE file_name = ?",
                    (file_name,)
                )
                result = cursor.fetchone()
                
                # Generate content hash
                content_hash = self._generate_content_hash(content)
                current_time = datetime.now().isoformat()
                
                if result:
                    # Document exists, check if content changed
                    document_id = result[0]
                    
                    # Get the latest version hash
                    cursor = self.conn.execute(
                        "SELECT content_hash FROM document_versions WHERE document_id = ? ORDER BY version_number DESC LIMIT 1",
                        (document_id,)
                    )
                    latest_hash_result = cursor.fetchone()
                    
                    if latest_hash_result and latest_hash_result[0] == content_hash:
                        # Content is the same, no new version needed
                        logger.info(f"Document {file_name} already exists with the same content")
                        
                        # Get the current version number
                        cursor = self.conn.execute(
                            "SELECT version_number FROM document_versions WHERE document_id = ? ORDER BY version_number DESC LIMIT 1",
                            (document_id,)
                        )
                        version_result = cursor.fetchone()
                        
                        return document_id, version_result[0]
                    
                    # Update the document metadata
                    self.conn.execute(
                        "UPDATE documents SET last_updated = ?, metadata = ? WHERE id = ?",
                        (current_time, json.dumps(metadata or {}), document_id)
                    )
                    
                    # Add new version
                    cursor = self.conn.execute(
                        "SELECT MAX(version_number) FROM document_versions WHERE document_id = ?",
                        (document_id,)
                    )
                    max_version = cursor.fetchone()[0] or 0
                    new_version = max_version + 1
                    
                    self.conn.execute(
                        "INSERT INTO document_versions (document_id, version_number, content_hash, content, added_date, comment) VALUES (?, ?, ?, ?, ?, ?)",
                        (document_id, new_version, content_hash, content, current_time, comment)
                    )
                    
                    logger.info(f"Added version {new_version} for document {file_name}")
                    return document_id, new_version
                
                else:
                    # New document
                    metadata_json = json.dumps(metadata or {})
                    cursor = self.conn.execute(
                        "INSERT INTO documents (file_name, title, source, document_type, added_date, last_updated, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (file_name, title, source, document_type, current_time, current_time, metadata_json)
                    )
                    document_id = cursor.lastrowid
                    
                    # Add first version
                    self.conn.execute(
                        "INSERT INTO document_versions (document_id, version_number, content_hash, content, added_date, comment) VALUES (?, ?, ?, ?, ?, ?)",
                        (document_id, 1, content_hash, content, current_time, comment or "Initial version")
                    )
                    
                    logger.info(f"Added new document {file_name} with id {document_id}")
                    return document_id, 1
                    
        except Exception as e:
            logger.error(f"Error adding document {file_name}: {str(e)}")
            raise
    
    def add_regulatory_clauses(self, document_id, version_number, clauses):
        """Add regulatory clauses for a document version"""
        try:
            with self.conn:
                # First delete any existing clauses for this document version
                self.conn.execute(
                    "DELETE FROM regulatory_clauses WHERE document_id = ? AND document_version = ?",
                    (document_id, version_number)
                )
                
                # Add the new clauses
                for clause in clauses:
                    metadata = {k: v for k, v in clause.items() if k not in [
                        'id', 'section', 'title', 'text', 'requirement_type', 'page_number'
                    ]}
                    
                    self.conn.execute(
                        """
                        INSERT INTO regulatory_clauses 
                        (document_id, document_version, clause_id, section, title, text, requirement_type, page_number, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            version_number,
                            clause.get('id', ''),
                            clause.get('section', ''),
                            clause.get('title', ''),
                            clause.get('text', ''),
                            clause.get('requirement_type', ''),
                            clause.get('page_number', ''),
                            json.dumps(metadata)
                        )
                    )
                
                logger.info(f"Added {len(clauses)} regulatory clauses for document {document_id} version {version_number}")
                
        except Exception as e:
            logger.error(f"Error adding regulatory clauses for document {document_id} version {version_number}: {str(e)}")
            raise
    
    def get_document(self, document_id, version_number=None):
        """Get document content and metadata"""
        try:
            with self.conn:
                # Get document metadata
                cursor = self.conn.execute(
                    "SELECT id, file_name, title, source, document_type, added_date, last_updated, metadata FROM documents WHERE id = ?",
                    (document_id,)
                )
                doc_result = cursor.fetchone()
                
                if not doc_result:
                    logger.warning(f"Document {document_id} not found")
                    return None
                
                document = {
                    "id": doc_result[0],
                    "file_name": doc_result[1],
                    "title": doc_result[2],
                    "source": doc_result[3],
                    "document_type": doc_result[4],
                    "added_date": doc_result[5],
                    "last_updated": doc_result[6],
                    "metadata": json.loads(doc_result[7] or '{}')
                }
                
                # Get the requested version or the latest
                if version_number:
                    version_query = "SELECT version_number, content, added_date, comment FROM document_versions WHERE document_id = ? AND version_number = ?"
                    version_params = (document_id, version_number)
                else:
                    version_query = "SELECT version_number, content, added_date, comment FROM document_versions WHERE document_id = ? ORDER BY version_number DESC LIMIT 1"
                    version_params = (document_id,)
                
                cursor = self.conn.execute(version_query, version_params)
                version_result = cursor.fetchone()
                
                if not version_result:
                    logger.warning(f"Version {version_number} for document {document_id} not found")
                    return document
                
                document["version"] = {
                    "number": version_result[0],
                    "content": version_result[1],
                    "added_date": version_result[2],
                    "comment": version_result[3]
                }
                
                return document
                
        except Exception as e:
            logger.error(f"Error getting document {document_id}: {str(e)}")
            raise
    
    def get_all_documents(self, include_latest_version=False):
        """Get all documents with optional latest version content"""
        try:
            with self.conn:
                cursor = self.conn.execute(
                    "SELECT id, file_name, title, source, document_type, added_date, last_updated, metadata FROM documents ORDER BY last_updated DESC"
                )
                documents = []
                
                for row in cursor.fetchall():
                    document = {
                        "id": row[0],
                        "file_name": row[1],
                        "title": row[2],
                        "source": row[3],
                        "document_type": row[4],
                        "added_date": row[5],
                        "last_updated": row[6],
                        "metadata": json.loads(row[7] or '{}')
                    }
                    
                    if include_latest_version:
                        version_cursor = self.conn.execute(
                            "SELECT version_number, added_date, comment FROM document_versions WHERE document_id = ? ORDER BY version_number DESC LIMIT 1",
                            (document["id"],)
                        )
                        version_result = version_cursor.fetchone()
                        
                        if version_result:
                            document["latest_version"] = {
                                "number": version_result[0],
                                "added_date": version_result[1],
                                "comment": version_result[2]
                            }
                    
                    documents.append(document)
                
                return documents
                
        except Exception as e:
            logger.error(f"Error getting all documents: {str(e)}")
            raise
    
    def get_document_versions(self, document_id):
        """Get all versions of a document without content"""
        try:
            with self.conn:
                cursor = self.conn.execute(
                    "SELECT version_number, content_hash, added_date, comment FROM document_versions WHERE document_id = ? ORDER BY version_number DESC",
                    (document_id,)
                )
                
                versions = []
                for row in cursor.fetchall():
                    versions.append({
                        "number": row[0],
                        "hash": row[1],
                        "added_date": row[2],
                        "comment": row[3]
                    })
                
                return versions
                
        except Exception as e:
            logger.error(f"Error getting versions for document {document_id}: {str(e)}")
            raise
    
    def get_regulatory_clauses(self, document_id, version_number=None):
        """Get regulatory clauses for a document version"""
        try:
            with self.conn:
                if version_number:
                    query = """
                    SELECT id, clause_id, section, title, text, requirement_type, page_number, metadata
                    FROM regulatory_clauses
                    WHERE document_id = ? AND document_version = ?
                    """
                    params = (document_id, version_number)
                else:
                    # Get clauses from latest version
                    query = """
                    SELECT rc.id, rc.clause_id, rc.section, rc.title, rc.text, rc.requirement_type, rc.page_number, rc.metadata
                    FROM regulatory_clauses rc
                    JOIN (
                        SELECT document_id, MAX(version_number) as max_version
                        FROM document_versions
                        WHERE document_id = ?
                        GROUP BY document_id
                    ) latest ON rc.document_id = latest.document_id AND rc.document_version = latest.max_version
                    WHERE rc.document_id = ?
                    """
                    params = (document_id, document_id)
                
                cursor = self.conn.execute(query, params)
                
                clauses = []
                for row in cursor.fetchall():
                    clauses.append({
                        "id": row[0],
                        "clause_id": row[1],
                        "section": row[2],
                        "title": row[3],
                        "text": row[4],
                        "requirement_type": row[5],
                        "page_number": row[6],
                        "metadata": json.loads(row[7] or '{}')
                    })
                
                return clauses
                
        except Exception as e:
            logger.error(f"Error getting clauses for document {document_id}: {str(e)}")
            raise
    
    def get_all_regulatory_clauses(self, latest_versions_only=True):
        """Get all regulatory clauses across all documents"""
        try:
            with self.conn:
                if latest_versions_only:
                    query = """
                    SELECT rc.id, rc.document_id, rc.document_version, rc.clause_id, rc.section, rc.title, rc.text, 
                           rc.requirement_type, rc.page_number, rc.metadata, d.file_name
                    FROM regulatory_clauses rc
                    JOIN documents d ON rc.document_id = d.id
                    JOIN (
                        SELECT document_id, MAX(version_number) as max_version
                        FROM document_versions
                        GROUP BY document_id
                    ) latest ON rc.document_id = latest.document_id AND rc.document_version = latest.max_version
                    """
                    params = ()
                else:
                    query = """
                    SELECT rc.id, rc.document_id, rc.document_version, rc.clause_id, rc.section, rc.title, rc.text, 
                           rc.requirement_type, rc.page_number, rc.metadata, d.file_name
                    FROM regulatory_clauses rc
                    JOIN documents d ON rc.document_id = d.id
                    """
                    params = ()
                
                cursor = self.conn.execute(query, params)
                
                clauses = []
                for row in cursor.fetchall():
                    clauses.append({
                        "id": row[0],
                        "document_id": row[1],
                        "document_version": row[2],
                        "clause_id": row[3],
                        "section": row[4],
                        "title": row[5],
                        "text": row[6],
                        "requirement_type": row[7],
                        "page_number": row[8],
                        "metadata": json.loads(row[9] or '{}'),
                        "source_document": row[10]
                    })
                
                return clauses
                
        except Exception as e:
            logger.error(f"Error getting all regulatory clauses: {str(e)}")
            raise
    
    def search_regulatory_clauses(self, search_text):
        """Search for regulatory clauses containing specific text"""
        try:
            with self.conn:
                # Using SQLite FTS would be better but for simplicity using LIKE
                query = """
                SELECT rc.id, rc.document_id, rc.document_version, rc.clause_id, rc.section, rc.title, rc.text, 
                       rc.requirement_type, rc.page_number, rc.metadata, d.file_name
                FROM regulatory_clauses rc
                JOIN documents d ON rc.document_id = d.id
                JOIN (
                    SELECT document_id, MAX(version_number) as max_version
                    FROM document_versions
                    GROUP BY document_id
                ) latest ON rc.document_id = latest.document_id AND rc.document_version = latest.max_version
                WHERE rc.text LIKE ? OR rc.title LIKE ? OR rc.section LIKE ?
                """
                search_pattern = f"%{search_text}%"
                params = (search_pattern, search_pattern, search_pattern)
                
                cursor = self.conn.execute(query, params)
                
                clauses = []
                for row in cursor.fetchall():
                    clauses.append({
                        "id": row[0],
                        "document_id": row[1],
                        "document_version": row[2],
                        "clause_id": row[3],
                        "section": row[4],
                        "title": row[5],
                        "text": row[6],
                        "requirement_type": row[7],
                        "page_number": row[8],
                        "metadata": json.loads(row[9] or '{}'),
                        "source_document": row[10]
                    })
                
                return clauses
                
        except Exception as e:
            logger.error(f"Error searching regulatory clauses for '{search_text}': {str(e)}")
            raise
    
    def _generate_content_hash(self, content):
        """Generate a hash of the document content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    