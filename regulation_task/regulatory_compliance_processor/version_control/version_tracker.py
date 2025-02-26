# version_control/version_tracker.py
import logging
from typing import List, Dict, Any

from ..knowledge_base.document_store import DocumentStore
from .diff_engine import DiffEngine

logger = logging.getLogger(__name__)

class VersionTracker:
    """Track and manage document versions"""
    
    def __init__(self, document_store: DocumentStore):
        self.document_store = document_store
        self.diff_engine = DiffEngine(document_store)
    
    def get_document_version_history(self, document_id: int) -> List[Dict[str, Any]]:
        """Get version history for a document"""
        try:
            versions = self.document_store.get_document_versions(document_id)
            document = self.document_store.get_document(document_id)
            
            # Add document info to result
            for version in versions:
                version["document_name"] = document.get("file_name", "")
            
            return versions
        except Exception as e:
            logger.error(f"Error getting version history for document {document_id}: {str(e)}")
            return []
    
    def compare_with_previous_version(self, document_id: int, version: int) -> Dict[str, Any]:
        """Compare a document version with its previous version"""
        try:
            if version <= 1:
                return {
                    "error": "This is the first version, no previous version to compare with",
                    "status": "failed"
                }
            
            # Compare with previous version
            return self.diff_engine.compare_document_versions(document_id, version - 1, version)
            
        except Exception as e:
            logger.error(f"Error comparing document {document_id} version {version} with previous: {str(e)}")
            return {
                "error": str(e),
                "status": "failed"
            }
    
    def get_latest_changes(self) -> List[Dict[str, Any]]:
        """Get latest changes across all documents"""
        try:
            # Get all documents with latest version info
            documents = self.document_store.get_all_documents(include_latest_version=True)
            
            latest_changes = []
            for document in documents:
                # Skip documents with only one version
                if document.get("latest_version", {}).get("number", 0) <= 1:
                    continue
                
                # Get latest version
                latest_version = document["latest_version"]["number"]
                
                # Compare with previous version
                comparison = self.diff_engine.compare_document_versions(
                    document["id"], 
                    latest_version - 1, 
                    latest_version
                )
                
                # Only include documents with significant changes
                if (comparison["clause_changes"]["stats"]["added_clauses"] > 0 or
                    comparison["clause_changes"]["stats"]["removed_clauses"] > 0 or
                    comparison["clause_changes"]["stats"]["modified_clauses"] > 0):
                    
                    latest_changes.append({
                        "document_id": document["id"],
                        "document_name": document["file_name"],
                        "latest_version": latest_version,
                        "version_date": document["latest_version"]["added_date"],
                        "changes": comparison
                    })
            
            return latest_changes
            
        except Exception as e:
            logger.error(f"Error getting latest changes: {str(e)}")
            return []
        