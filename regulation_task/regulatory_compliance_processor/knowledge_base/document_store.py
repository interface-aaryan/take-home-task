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
            # Documents table - intentionally without status field for upgrade
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
            
            # Migrate database by adding status column if it doesn't exist
            try:
                # Check if status column exists
                cursor = conn.execute("SELECT status FROM documents LIMIT 1")
                cursor.fetchone()  # This will throw an exception if status doesn't exist
            except sqlite3.OperationalError:
                # Status column doesn't exist, add it
                logger.info("Migrating database: Adding status column to documents table")
                conn.execute("ALTER TABLE documents ADD COLUMN status TEXT DEFAULT 'completed'")
                conn.commit()
                logger.info("Database migration completed successfully")
            except Exception:
                # If fetching failed for other reasons (empty table), that's fine
                pass
            
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
            
            # SOP analysis records table
            conn.execute('''
            CREATE TABLE IF NOT EXISTS sop_analyses (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                result_json TEXT
            )
            ''')
        
        return conn
    
    def _normalize_filename(self, file_name):
        """
        Normalize a filename to ensure consistent matching regardless of special characters
        
        Args:
            file_name: Name of the file to normalize
            
        Returns:
            Normalized filename for matching purposes
        """
        # Remove special characters that might cause inconsistent matching
        import re
        # Replace underscores, spaces, and hyphens with a single space, then remove other special chars
        normalized = re.sub(r'[_\-\s]+', ' ', file_name)
        # Further normalize by removing any remaining non-alphanumeric chars and converting to lowercase
        normalized = re.sub(r'[^a-zA-Z0-9\s]', '', normalized).strip().lower()
        return normalized
        
    def add_document(self, file_name, content, title=None, source=None, document_type=None, metadata=None, comment=None, status="completed"):
        """
        Add a new document or a new version of an existing document
        
        Args:
            file_name: Name of the file
            content: Document content
            title: Document title
            source: Document source
            document_type: Type of document
            metadata: Additional metadata as dict
            comment: Version comment
            status: Document processing status (completed, processing, failed)
            
        Returns:
            Tuple (document_id, version_number)
        """
        try:
            # Normalize the filename for consistent matching
            normalized_filename = self._normalize_filename(file_name)
            
            # Check if document already exists by normalized filename
            with self.conn:
                cursor = self.conn.execute(
                    "SELECT id, file_name FROM documents WHERE file_name = ? OR file_name LIKE ?", 
                    (file_name, f"%{normalized_filename}%")
                )
                results = cursor.fetchall()
                
                # Check content hash for exact matches
                content_hash = self._generate_content_hash(content)
                current_time = datetime.now().isoformat()
                
                # If we found possible matches by filename
                if results:
                    # Check through potential document matches
                    for result in results:
                        document_id = result[0]
                        existing_filename = result[1]
                        
                        # Get the latest version hash
                        cursor = self.conn.execute(
                            "SELECT content_hash FROM document_versions WHERE document_id = ? ORDER BY version_number DESC LIMIT 1",
                            (document_id,)
                        )
                        latest_hash_result = cursor.fetchone()
                        
                        if latest_hash_result and latest_hash_result[0] == content_hash:
                            # Content is the same, no new version needed
                            logger.info(f"Document {file_name} matches existing document {existing_filename} with the same content")
                            
                            # Get the current version number
                            cursor = self.conn.execute(
                                "SELECT version_number FROM document_versions WHERE document_id = ? ORDER BY version_number DESC LIMIT 1",
                                (document_id,)
                            )
                            version_result = cursor.fetchone()
                            
                            # Update filename if it's different to keep the record clean
                            if existing_filename != file_name:
                                self.conn.execute(
                                    "UPDATE documents SET file_name = ?, last_updated = ? WHERE id = ?",
                                    (file_name, current_time, document_id)
                                )
                                logger.info(f"Updated filename from {existing_filename} to {file_name}")
                            
                            return document_id, version_result[0]
                    
                    # If we reach here, no content match was found
                    # Use the first match as our document ID to update with new version
                    document_id = results[0][0]
                    logger.info(f"Document similar to {file_name} exists but content differs - creating new version")
                
                    # Update the document metadata, filename and status
                    self.conn.execute(
                        "UPDATE documents SET file_name = ?, last_updated = ?, metadata = ?, status = ? WHERE id = ?",
                        (file_name, current_time, json.dumps(metadata or {}), status, document_id)
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
                        "INSERT INTO documents (file_name, title, source, document_type, added_date, last_updated, metadata, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (file_name, title, source, document_type, current_time, current_time, metadata_json, status)
                    )
                    document_id = cursor.lastrowid
                    
                    # Add first version
                    self.conn.execute(
                        "INSERT INTO document_versions (document_id, version_number, content_hash, content, added_date, comment) VALUES (?, ?, ?, ?, ?, ?)",
                        (document_id, 1, content_hash, content, current_time, comment or "Initial version")
                    )
                    
                    logger.info(f"Added new document {file_name} with id {document_id} and status {status}")
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
                # Check if status column exists in documents table
                status_exists = True
                try:
                    self.conn.execute("SELECT status FROM documents LIMIT 1")
                except sqlite3.OperationalError:
                    status_exists = False
                
                # Get document metadata, with or without status
                if status_exists:
                    query = "SELECT id, file_name, title, source, document_type, added_date, last_updated, metadata, status FROM documents WHERE id = ?"
                else:
                    query = "SELECT id, file_name, title, source, document_type, added_date, last_updated, metadata FROM documents WHERE id = ?"
                
                cursor = self.conn.execute(query, (document_id,))
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
                
                if status_exists and len(doc_result) > 8:
                    document["status"] = doc_result[8] or "completed"
                else:
                    document["status"] = "completed"
                
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
                # Check if status column exists in documents table
                status_exists = True
                try:
                    self.conn.execute("SELECT status FROM documents LIMIT 1")
                except sqlite3.OperationalError:
                    status_exists = False
                
                # Get all documents, with or without status
                if status_exists:
                    query = "SELECT id, file_name, title, source, document_type, added_date, last_updated, metadata, status FROM documents ORDER BY last_updated DESC"
                else:
                    query = "SELECT id, file_name, title, source, document_type, added_date, last_updated, metadata FROM documents ORDER BY last_updated DESC"
                
                cursor = self.conn.execute(query)
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
                    
                    # Add status if available
                    if status_exists and len(row) > 8:
                        document["status"] = row[8] or "completed"
                    else:
                        document["status"] = "completed"
                    
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
            
    def update_document_status(self, document_id, status):
        """Update the processing status of a document"""
        try:
            with self.conn:
                # Check if status column exists
                status_exists = True
                try:
                    self.conn.execute("SELECT status FROM documents LIMIT 1")
                except sqlite3.OperationalError:
                    status_exists = False
                    
                # Add status column if needed
                if not status_exists:
                    logger.info(f"Adding status column to documents table before updating status")
                    self.conn.execute("ALTER TABLE documents ADD COLUMN status TEXT DEFAULT 'completed'")
                    self.conn.commit()
                
                # Update status
                self.conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ?",
                    (status, document_id)
                )
                logger.info(f"Updated document {document_id} status to '{status}'")
                return True
        except Exception as e:
            logger.error(f"Error updating document {document_id} status: {str(e)}")
            return False
            
    def get_document_status(self, document_id):
        """Get the processing status of a document"""
        try:
            with self.conn:
                # Check if status column exists
                status_exists = True
                try:
                    self.conn.execute("SELECT status FROM documents LIMIT 1")
                except sqlite3.OperationalError:
                    status_exists = False
                    
                # Add status column if needed
                if not status_exists:
                    logger.info(f"Adding status column to documents table before getting status")
                    self.conn.execute("ALTER TABLE documents ADD COLUMN status TEXT DEFAULT 'completed'")
                    self.conn.commit()
                
                # Get status
                cursor = self.conn.execute(
                    "SELECT status FROM documents WHERE id = ?",
                    (document_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else "completed"
        except Exception as e:
            logger.error(f"Error getting document {document_id} status: {str(e)}")
            return "completed"
            
    def add_sop_analysis(self, analysis_id, filename, status, result_json=None):
        """
        Add or update a SOP analysis record
        
        Args:
            analysis_id: Unique ID for the analysis
            filename: Name of the analyzed file
            status: Status of the analysis (processing, completed, failed)
            result_json: JSON string of analysis results (can be None for processing state)
            
        Returns:
            bool: True if successful
        """
        try:
            current_time = datetime.now().isoformat()
            with self.conn:
                # Check if record already exists
                cursor = self.conn.execute(
                    "SELECT id FROM sop_analyses WHERE id = ?", (analysis_id,)
                )
                result = cursor.fetchone()
                
                if result:
                    # Update existing record
                    self.conn.execute(
                        """
                        UPDATE sop_analyses 
                        SET status = ?, updated_at = ?, result_json = COALESCE(?, result_json)
                        WHERE id = ?
                        """,
                        (status, current_time, result_json, analysis_id)
                    )
                else:
                    # Insert new record
                    self.conn.execute(
                        """
                        INSERT INTO sop_analyses (id, filename, status, created_at, updated_at, result_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (analysis_id, filename, status, current_time, current_time, result_json or "")
                    )
                
                logger.info(f"Saved SOP analysis record for {filename} with status {status}")
                return True
        except Exception as e:
            logger.error(f"Error saving SOP analysis record: {str(e)}")
            return False
            
    def get_sop_analysis(self, analysis_id):
        """
        Get a SOP analysis record by ID
        
        Args:
            analysis_id: Analysis ID
            
        Returns:
            dict: Analysis record or None if not found
        """
        try:
            with self.conn:
                cursor = self.conn.execute(
                    "SELECT id, filename, status, created_at, updated_at, result_json FROM sop_analyses WHERE id = ?",
                    (analysis_id,)
                )
                result = cursor.fetchone()
                
                if result:
                    return {
                        "id": result[0],
                        "filename": result[1],
                        "status": result[2],
                        "created_at": result[3],
                        "updated_at": result[4],
                        "result_json": result[5]
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting SOP analysis {analysis_id}: {str(e)}")
            return None
            
    def get_all_sop_analyses(self, limit=None):
        """
        Get all SOP analyses, optionally limited to a number of records
        
        Args:
            limit: Maximum number of records to return, ordered by updated_at
            
        Returns:
            list: Analysis records
        """
        try:
            with self.conn:
                query = "SELECT id, filename, status, created_at, updated_at FROM sop_analyses ORDER BY updated_at DESC"
                if limit:
                    query += f" LIMIT {int(limit)}"
                    
                cursor = self.conn.execute(query)
                results = []
                
                for row in cursor.fetchall():
                    results.append({
                        "id": row[0],
                        "filename": row[1],
                        "status": row[2],
                        "created_at": row[3],
                        "updated_at": row[4]
                    })
                    
                return results
        except Exception as e:
            logger.error(f"Error getting SOP analyses: {str(e)}")
            return []
            
    def update_sop_analysis_status(self, analysis_id, status):
        """
        Update the status of a SOP analysis
        
        Args:
            analysis_id: Analysis ID
            status: New status (processing, completed, failed)
            
        Returns:
            bool: True if successful
        """
        try:
            with self.conn:
                current_time = datetime.now().isoformat()
                self.conn.execute(
                    "UPDATE sop_analyses SET status = ?, updated_at = ? WHERE id = ?",
                    (status, current_time, analysis_id)
                )
                logger.info(f"Updated SOP analysis {analysis_id} status to {status}")
                return True
        except Exception as e:
            logger.error(f"Error updating SOP analysis status: {str(e)}")
            return False
    
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
    
    def completely_delete_document(self, document_id):
        """
        Completely delete a document and all its versions and related data
        
        Args:
            document_id: ID of the document to completely delete
            
        Returns:
            Tuple (success, num_clauses_deleted)
        """
        try:
            with self.conn:
                # First count how many clauses we're deleting for reporting
                cursor = self.conn.execute(
                    "SELECT COUNT(*) FROM regulatory_clauses WHERE document_id = ?",
                    (document_id,)
                )
                clauses_count = cursor.fetchone()[0] or 0
                
                # Delete all clauses for this document
                cursor = self.conn.execute(
                    "DELETE FROM regulatory_clauses WHERE document_id = ?",
                    (document_id,)
                )
                
                # Delete all versions for this document
                cursor = self.conn.execute(
                    "DELETE FROM document_versions WHERE document_id = ?",
                    (document_id,)
                )
                
                # Finally delete the document itself
                cursor = self.conn.execute(
                    "DELETE FROM documents WHERE id = ?",
                    (document_id,)
                )
                
                logger.info(f"Completely deleted document ID {document_id} with {clauses_count} clauses")
                return True, clauses_count
                
        except Exception as e:
            logger.error(f"Error completely deleting document {document_id}: {str(e)}")
            return False, 0
    
    def _generate_content_hash(self, content):
        """Generate a hash of the document content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    