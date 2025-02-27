# analysis/compliance_analyzer.py
import logging
import json
import time
import gc
from typing import List, Dict, Any, Optional

from ..config import GPT_MODEL, openai_client, RELEVANCE_THRESHOLD, MAX_RELEVANT_CLAUSES, USE_LANGCHAIN
from ..knowledge_base.vector_store_factory import VectorStoreFactory

logger = logging.getLogger(__name__)

class ComplianceAnalyzer:
    """Analyze SOP compliance against regulatory clauses"""
    
    def __init__(self, vector_store=None, model=GPT_MODEL, use_langchain=None):
        self.model = model
        # If no vector store is provided, create one using the factory
        if vector_store is None:
            self.vector_store = VectorStoreFactory.create_vector_store(use_langchain)
        else:
            self.vector_store = vector_store
    
    def analyze_sop_compliance(self, sop_content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze SOP compliance against relevant regulatory clauses
        
        Args:
            sop_content: Dict containing SOP text and metadata
            
        Returns:
            Dict containing compliance analysis results
        """
        # Step 1: Extract key sections from SOP
        sop_sections = self._extract_sop_sections(sop_content["text"])
        
        # Step 2: Find relevant regulatory clauses using vector search
        relevant_clauses = self._find_relevant_clauses(sop_sections)
        
        # Step 3: Perform detailed compliance analysis
        compliance_analysis = self._analyze_compliance(sop_content["text"], relevant_clauses)
        
        # Step 4: Generate recommendations for SOP improvements
        recommendations = self._generate_recommendations(compliance_analysis, sop_content["text"])
        
        # Compile final analysis report
        analysis_report = {
            "sop": {
                "file_name": sop_content.get("file_name", ""),
                "sections": sop_sections
            },
            "relevant_clauses": relevant_clauses,
            "compliance_analysis": compliance_analysis,
            "recommendations": recommendations,
            "summary": self._generate_summary(compliance_analysis, recommendations)
        }
        
        return analysis_report
    
    def _extract_sop_sections(self, sop_text: str) -> List[Dict[str, Any]]:
        """Extract key sections from SOP text using LLM"""
        prompt = f"""
Extract the key sections from the following Standard Operating Procedure (SOP).
For each section, identify:
1. The section title
2. The section content
3. Any specific requirements or procedures mentioned

Respond with a JSON object with this structure:
{{
  "sections": [
    {{
      "title": "section title",
      "content": "section content",
      "requirements": ["requirement 1", "requirement 2", ...],
    }},
    ...more sections...
  ]
}}

Here's the SOP text:
{sop_text[:10000]}  # Truncate to avoid token limits
"""
        
        try:
            response = openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a regulatory compliance expert that specializes in analyzing Standard Operating Procedures (SOPs) and extracting key sections."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0
            )
            
            # Extract and parse the response
            response_text = response.choices[0].message.content
            
            try:
                sections_data = json.loads(response_text)
                sections = sections_data.get("sections", [])
                
                # If SOP is long, process remaining text in chunks
                if len(sop_text) > 10000:
                    remaining_chunks = [sop_text[i:i+10000] for i in range(10000, len(sop_text), 10000)]
                    
                    for i, chunk in enumerate(remaining_chunks):
                        chunk_prompt = f"""
Continue extracting key sections from this SOP. Here's the next part:
{chunk}

Respond with a JSON object with the same structure as before.
"""
                        
                        chunk_response = openai_client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": "You are a regulatory compliance expert that specializes in analyzing Standard Operating Procedures (SOPs) and extracting key sections."},
                                {"role": "user", "content": chunk_prompt}
                            ],
                            response_format={"type": "json_object"},
                            temperature=0
                        )
                        
                        chunk_text = chunk_response.choices[0].message.content
                        try:
                            chunk_data = json.loads(chunk_text)
                            sections.extend(chunk_data.get("sections", []))
                            
                            # Sleep to avoid rate limits
                            if i < len(remaining_chunks) - 1:
                                time.sleep(1)
                        except json.JSONDecodeError:
                            logger.error(f"Error parsing JSON from chunk {i+1}")
                
                return sections
                
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON for SOP sections: {str(e)}")
                return []
                
        except Exception as e:
            logger.error(f"Error extracting SOP sections: {str(e)}")
            return []
    
    def _find_relevant_clauses(self, sop_sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find regulatory clauses relevant to SOP sections"""
        if not sop_sections:
            logger.warning("No SOP sections provided for finding relevant clauses")
            return []
        
        # Create queries from section titles and content
        queries = []
        for section in sop_sections:
            # Add section title as query
            if section.get("title"):
                queries.append(section["title"])
            
            # Add requirements as individual queries
            if section.get("requirements"):
                for req in section["requirements"]:
                    if len(req) > 10:  # Skip very short requirements
                        queries.append(req)
        
        # If we have too many queries, select the most important ones
        if len(queries) > 20:
            # Keep section titles and truncate requirements
            section_titles = [section["title"] for section in sop_sections if section.get("title")]
            selected_queries = section_titles + queries[len(section_titles):20]
            queries = selected_queries
        
        # Use vector store to find relevant clauses
        all_results = []
        for query in queries:
            results = self.vector_store.search(query, k=5)  # Get top 5 results per query
            all_results.extend(results)
        
        # Deduplicate and keep only clauses with similarity above threshold
        seen_clauses = set()
        deduplicated_results = []
        
        for result in all_results:
            # Skip clauses with low similarity
            if result.get("similarity", 0) < RELEVANCE_THRESHOLD:
                continue
                
            # Skip duplicates
            clause_id = f"{result.get('document_id')}_{result.get('id')}"
            if clause_id in seen_clauses:
                continue
                
            seen_clauses.add(clause_id)
            deduplicated_results.append(result)
        
        # Sort by similarity and limit to maximum number
        sorted_results = sorted(deduplicated_results, key=lambda x: x.get("similarity", 0), reverse=True)
        top_results = sorted_results[:MAX_RELEVANT_CLAUSES]
        
        return top_results
    
    def _analyze_compliance(self, sop_text: str, relevant_clauses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Analyze SOP compliance against each relevant regulatory clause"""
        if not relevant_clauses:
            logger.warning("No relevant clauses provided for compliance analysis")
            return []
        
        # Process clauses in batches to avoid context length issues
        analysis_results = []
        batch_size = 5  # Process 5 clauses at a time
        
        for i in range(0, len(relevant_clauses), batch_size):
            batch_clauses = relevant_clauses[i:i + batch_size]
            
            # Create clause descriptions for the prompt
            clauses_text = ""
            for j, clause in enumerate(batch_clauses):
                clauses_text += f"CLAUSE {j+1}:\n"
                clauses_text += f"Source: {clause.get('source_document', 'Unknown')}\n"
                if clause.get('section'):
                    clauses_text += f"Section: {clause['section']}\n"
                if clause.get('title'):
                    clauses_text += f"Title: {clause['title']}\n"
                clauses_text += f"Text: {clause['text']}\n\n"
            
            # Create analysis prompt
            prompt = f"""
Analyze whether the following SOP complies with each of the regulatory clauses.
For each clause, determine:
1. Is the SOP compliant with this clause? (Yes/No/Partial)
2. What specific parts of the SOP address this clause, if any?
3. What specific requirements from the clause are not met by the SOP, if any?
4. Severity of non-compliance (High/Medium/Low) if not fully compliant

SOP:
{sop_text[:10000]}  # Truncate to avoid token limits

Regulatory Clauses:
{clauses_text}

Respond with a JSON object with this structure:
{{
  "analyses": [
    {{
      "clause_index": 1,
      "compliance_status": "Yes/No/Partial",
      "addressed_by": "specific part of SOP that addresses this",
      "missing_requirements": ["requirement 1 not met", "requirement 2 not met"],
      "severity": "High/Medium/Low",
      "explanation": "detailed explanation of compliance analysis"
    }},
    ...more analyses...
  ]
}}
"""
            
            try:
                response = openai_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a regulatory compliance expert that specializes in analyzing whether SOPs comply with regulatory requirements."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0
                )
                
                # Extract and parse the response
                response_text = response.choices[0].message.content
                
                try:
                    analyses_data = json.loads(response_text)
                    batch_analyses = analyses_data.get("analyses", [])
                    
                    # Add original clause data to each analysis
                    for analysis in batch_analyses:
                        clause_idx = analysis.get("clause_index", 0) - 1
                        if 0 <= clause_idx < len(batch_clauses):
                            clause = batch_clauses[clause_idx]
                            analysis["clause"] = {
                                "id": clause.get("id"),
                                "document_id": clause.get("document_id"),
                                "section": clause.get("section"),
                                "title": clause.get("title"),
                                "text": clause.get("text"),
                                "source_document": clause.get("source_document")
                            }
                    
                    analysis_results.extend(batch_analyses)
                    
                    # Sleep to avoid rate limits
                    if i + batch_size < len(relevant_clauses):
                        time.sleep(1)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing JSON for compliance analysis: {str(e)}")
                    logger.error(f"Response text: {response_text}")
                
            except Exception as e:
                logger.error(f"Error analyzing compliance for batch {i // batch_size + 1}: {str(e)}")
        
        return analysis_results
    
    def _generate_recommendations(self, compliance_analyses: List[Dict[str, Any]], sop_text: str) -> Dict[str, Any]:
        """Generate recommendations for SOP improvements based on compliance analysis"""
        if not compliance_analyses:
            logger.warning("No compliance analyses provided for generating recommendations")
            return {
                "summary": "No recommendations available due to lack of compliance analyses",
                "improvements": []
            }
        
        # Filter analyses that have compliance issues
        non_compliant = [a for a in compliance_analyses if a.get("compliance_status") != "Yes"]
        
        if not non_compliant:
            return {
                "summary": "The SOP appears to be fully compliant with all relevant regulatory clauses.",
                "improvements": []
            }
        
        # Create recommendation prompt
        non_compliant_text = ""
        for i, analysis in enumerate(non_compliant):
            clause = analysis.get("clause", {})
            non_compliant_text += f"ISSUE {i+1}:\n"
            non_compliant_text += f"Source: {clause.get('source_document', 'Unknown')}\n"
            non_compliant_text += f"Section: {clause.get('section', 'Unknown')}\n"
            non_compliant_text += f"Requirement: {clause.get('text', 'Unknown')}\n"
            non_compliant_text += f"Compliance Status: {analysis.get('compliance_status', 'Unknown')}\n"
            non_compliant_text += f"Missing Requirements: {', '.join(analysis.get('missing_requirements', []))}\n"
            non_compliant_text += f"Severity: {analysis.get('severity', 'Unknown')}\n\n"
        
        prompt = f"""
Based on the compliance issues identified, generate specific recommendations to improve the SOP.
For each recommendation, provide:
1. The specific change to make
2. The rationale for the change
3. The priority level (High/Medium/Low)
4. The regulatory clause that the change addresses

SOP issues:
{non_compliant_text}

Respond with a JSON object with this structure:
{{
  "summary": "brief summary of overall recommendations",
  "improvements": [
    {{
      "change": "specific description of what needs to be changed",
      "rationale": "why this change is needed",
      "priority": "High/Medium/Low",
      "reference_clause": "which regulatory clause this addresses",
      "implementation_guidance": "guidance on how to implement the change"
    }},
    ...more improvements...
  ]
}}
"""
        
        try:
            response = openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a regulatory compliance expert that specializes in developing recommendations to improve SOPs to ensure regulatory compliance."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0
            )
            
            # Extract and parse the response
            response_text = response.choices[0].message.content
            
            try:
                recommendations = json.loads(response_text)
                return recommendations
                
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON for recommendations: {str(e)}")
                return {
                    "summary": "Error generating recommendations",
                    "improvements": []
                }
                
        except Exception as e:
            logger.error(f"Error generating recommendations: {str(e)}")
            return {
                "summary": "Error generating recommendations",
                "improvements": []
            }
    
    def _generate_summary(self, compliance_analyses: List[Dict[str, Any]], recommendations: Dict[str, Any]) -> Dict[str, Any]:
        """Generate an executive summary of the compliance analysis"""
        
        # Count compliance statuses
        total_clauses = len(compliance_analyses)
        compliant = sum(1 for a in compliance_analyses if a.get("compliance_status") == "Yes")
        partially_compliant = sum(1 for a in compliance_analyses if a.get("compliance_status") == "Partial")
        non_compliant = sum(1 for a in compliance_analyses if a.get("compliance_status") == "No")
        
        # Count severity levels for non-compliant items
        high_severity = sum(1 for a in compliance_analyses if a.get("severity") == "High" and a.get("compliance_status") != "Yes")
        medium_severity = sum(1 for a in compliance_analyses if a.get("severity") == "Medium" and a.get("compliance_status") != "Yes")
        low_severity = sum(1 for a in compliance_analyses if a.get("severity") == "Low" and a.get("compliance_status") != "Yes")
        
        # Calculate compliance percentage
        compliance_percentage = (compliant + (partially_compliant * 0.5)) / total_clauses * 100 if total_clauses > 0 else 0
        
        # Determine overall compliance status
        if compliance_percentage >= 90:
            status = "Highly Compliant"
        elif compliance_percentage >= 75:
            status = "Substantially Compliant"
        elif compliance_percentage >= 50:
            status = "Partially Compliant"
        else:
            status = "Significantly Non-Compliant"
        
        # Get improvement counts by priority
        improvements = recommendations.get("improvements", [])
        high_priority = sum(1 for i in improvements if i.get("priority") == "High")
        medium_priority = sum(1 for i in improvements if i.get("priority") == "Medium")
        low_priority = sum(1 for i in improvements if i.get("priority") == "Low")
        
        summary = {
            "status": status,
            "compliance_percentage": round(compliance_percentage, 2),
            "clause_counts": {
                "total": total_clauses,
                "compliant": compliant,
                "partially_compliant": partially_compliant,
                "non_compliant": non_compliant
            },
            "severity_counts": {
                "high": high_severity,
                "medium": medium_severity,
                "low": low_severity
            },
            "improvement_counts": {
                "total": len(improvements),
                "high_priority": high_priority,
                "medium_priority": medium_priority,
                "low_priority": low_priority
            }
        }
        
        return summary
    