# version_control/diff_engine.py
import difflib
import logging
import json
from typing import List, Dict, Any, Tuple
import re

from ..knowledge_base.document_store import DocumentStore

logger = logging.getLogger(__name__)

class DiffEngine:
    """Engine for comparing different versions of regulatory documents"""
    
    def __init__(self, document_store: DocumentStore):
        self.document_store = document_store
    
    def compare_document_versions(self, document_id: int, version1: int, version2: int) -> Dict[str, Any]:
        """
        Compare two versions of a document and identify changes
        
        Args:
            document_id: Document identifier
            version1: First version number
            version2: Second version number
            
        Returns:
            Dict containing change summary
        """
        # Get the document versions
        doc_v1 = self.document_store.get_document(document_id, version1)
        doc_v2 = self.document_store.get_document(document_id, version2)
        
        if not doc_v1 or not doc_v2:
            logger.error(f"Could not retrieve both document versions for comparison")
            return {
                "error": "One or both document versions not found",
                "status": "failed"
            }
        
        # Get text content
        text_v1 = doc_v1["version"]["content"]
        text_v2 = doc_v2["version"]["content"]
        
        # Compare text
        diff_result = self._text_diff(text_v1, text_v2)
        
        # Compare regulatory clauses
        clauses_v1 = self.document_store.get_regulatory_clauses(document_id, version1)
        clauses_v2 = self.document_store.get_regulatory_clauses(document_id, version2)
        
        clause_diff = self._clause_diff(clauses_v1, clauses_v2)
        
        # Create comparison report
        comparison = {
            "document_id": document_id,
            "document_name": doc_v1.get("file_name", ""),
            "version_comparison": {
                "from_version": version1,
                "to_version": version2,
                "from_date": doc_v1["version"].get("added_date", ""),
                "to_date": doc_v2["version"].get("added_date", ""),
            },
            "text_changes": diff_result,
            "clause_changes": clause_diff,
            "metadata_changes": self._metadata_diff(doc_v1.get("metadata", {}), doc_v2.get("metadata", {}))
        }
        
        return comparison
    
    def _text_diff(self, text1: str, text2: str) -> Dict[str, Any]:
        """Compare two text versions and identify changes"""
        # Split into lines
        lines1 = text1.splitlines()
        lines2 = text2.splitlines()
        
        # Calculate diff
        differ = difflib.Differ()
        diff = list(differ.compare(lines1, lines2))
        
        # Extract changes
        additions = [line[2:] for line in diff if line.startswith('+ ')]
        deletions = [line[2:] for line in diff if line.startswith('- ')]
        
        # Create unified diff for visualization
        unified_diff = '\n'.join(difflib.unified_diff(
            lines1, lines2, 
            fromfile=f'version1', 
            tofile=f'version2',
            lineterm=''
        ))
        
        # Calculate stats
        total_lines_v1 = len(lines1)
        total_lines_v2 = len(lines2)
        added_lines = len(additions)
        removed_lines = len(deletions)
        change_percentage = round((added_lines + removed_lines) / max(total_lines_v1, total_lines_v2) * 100, 2)
        
        return {
            "unified_diff": unified_diff,
            "stats": {
                "lines_in_version1": total_lines_v1,
                "lines_in_version2": total_lines_v2,
                "added_lines": added_lines,
                "removed_lines": removed_lines,
                "change_percentage": change_percentage
            },
            "significant_changes": self._extract_significant_changes(diff)
        }
    
    def _extract_significant_changes(self, diff_lines: List[str]) -> List[Dict[str, Any]]:
        """Extract significant changes from diff lines (sections, requirements, etc.)"""
        significant_changes = []
        current_section = None
        section_changes = []
        
        # Pattern to identify section headers in the text
        section_pattern = re.compile(r'^[-+] [#\d\.]+ .*$|^[-+] .*[Ss]ection.*:|^[-+] .*[Cc]lause.*:')
        
        for line in diff_lines:
            if section_pattern.match(line):
                # If we found a new section and we have previous section changes, add them
                if current_section and section_changes:
                    significant_changes.append({
                        "section": current_section,
                        "changes": section_changes
                    })
                    section_changes = []
                
                # Set the new current section
                current_section = line[2:]
                
            # Add changes to the current section if it's an added or removed line
            if line.startswith('+ ') or line.startswith('- '):
                if current_section:
                    section_changes.append({
                        "type": "addition" if line.startswith('+ ') else "deletion",
                        "text": line[2:]
                    })
        
        # Add the last section if any
        if current_section and section_changes:
            significant_changes.append({
                "section": current_section,
                "changes": section_changes
            })
        
        return significant_changes
    
    def _clause_diff(self, clauses1: List[Dict[str, Any]], clauses2: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare two sets of regulatory clauses and identify changes"""
        # Create maps for easier comparison
        clause_map1 = {self._clause_key(c): c for c in clauses1}
        clause_map2 = {self._clause_key(c): c for c in clauses2}
        
        # Identify added, removed, and modified clauses
        added_keys = set(clause_map2.keys()) - set(clause_map1.keys())
        removed_keys = set(clause_map1.keys()) - set(clause_map2.keys())
        
        common_keys = set(clause_map1.keys()) & set(clause_map2.keys())
        modified_keys = {k for k in common_keys if self._is_clause_modified(clause_map1[k], clause_map2[k])}
        
        # Prepare result
        added_clauses = [clause_map2[k] for k in added_keys]
        removed_clauses = [clause_map1[k] for k in removed_keys]
        modified_clauses = [
            {
                "from": clause_map1[k],
                "to": clause_map2[k],
                "changes": self._get_clause_changes(clause_map1[k], clause_map2[k])
            }
            for k in modified_keys
        ]
        
        return {
            "added": added_clauses,
            "removed": removed_clauses,
            "modified": modified_clauses,
            "stats": {
                "clauses_in_version1": len(clauses1),
                "clauses_in_version2": len(clauses2),
                "added_clauses": len(added_clauses),
                "removed_clauses": len(removed_clauses),
                "modified_clauses": len(modified_clauses),
                "unchanged_clauses": len(common_keys) - len(modified_keys)
            }
        }
    
    def _clause_key(self, clause: Dict[str, Any]) -> str:
        """Generate a key for a clause based on its content"""
        # Use section and title if available, otherwise use the first 100 chars of text
        section = clause.get("section", "")
        title = clause.get("title", "")
        
        if section and title:
            return f"{section}:{title}"
        elif section:
            return f"{section}:{clause['text'][:50]}"
        elif title:
            return f"{title}:{clause['text'][:50]}"
        else:
            # Use a hash of the first 100 chars as a fallback
            text_sample = clause['text'][:100]
            return f"text:{hash(text_sample)}"
    
    def _is_clause_modified(self, clause1: Dict[str, Any], clause2: Dict[str, Any]) -> bool:
        """Check if a clause was modified between versions"""
        # Compare text content
        if clause1.get("text", "") != clause2.get("text", ""):
            return True
        
        # Compare requirement type
        if clause1.get("requirement_type", "") != clause2.get("requirement_type", ""):
            return True
        
        return False
    
    def _get_clause_changes(self, clause1: Dict[str, Any], clause2: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get detailed changes between two versions of a clause"""
        changes = []
        
        # Check for text changes
        if clause1.get("text", "") != clause2.get("text", ""):
            text_diff = difflib.unified_diff(
                clause1.get("text", "").splitlines(),
                clause2.get("text", "").splitlines(),
                lineterm=''
            )
            changes.append({
                "field": "text",
                "diff": '\n'.join(text_diff)
            })
        
        # Check for requirement type changes
        if clause1.get("requirement_type", "") != clause2.get("requirement_type", ""):
            changes.append({
                "field": "requirement_type",
                "from": clause1.get("requirement_type", ""),
                "to": clause2.get("requirement_type", "")
            })
        
        return changes
    
    def _metadata_diff(self, metadata1: Dict[str, Any], metadata2: Dict[str, Any]) -> Dict[str, Any]:
        """Compare metadata between document versions"""
        all_keys = set(metadata1.keys()) | set(metadata2.keys())
        
        changes = {}
        for key in all_keys:
            val1 = metadata1.get(key)
            val2 = metadata2.get(key)
            
            if val1 != val2:
                changes[key] = {
                    "from": val1,
                    "to": val2
                }
        
        return changes
