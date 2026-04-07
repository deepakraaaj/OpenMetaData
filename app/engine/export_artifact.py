import json
import logging
from app.models.state import KnowledgeState
from app.engine.ai_resolver import group_tables_by_relationships

logger = logging.getLogger(__name__)

def generate_llm_domain_artifact(state: KnowledgeState) -> dict:
    """
    Compiles the raw KnowledgeState into a hyper-dense, Domain-Driven artifact
    optimized specifically for LLM text generation and Text-to-SQL tasks.
    It groups raw tables into 'Entities/Domains' to prevent hallucination.
    """
    # 1. Group the tables into domains (same logic as the UI)
    groups = group_tables_by_relationships(state)
    
    artifact = {
        "_meta": {
            "source": state.source_name,
            "purpose": "LLM Semantic Context Artifact",
            "readiness_score": state.readiness.readiness_percentage
        },
        "domains": {}
    }

    # 2. Build out domain entries
    for domain_name, tables in groups.items():
        domain_payload = {
            "core_tables": [],
            "satellite_tables": [],
            "business_metrics": [],
            "verified_joins": [],
            "enumerations": {}
        }
        
        # Determine the core hub vs satellites based on join count
        table_objs = [state.tables[t] for t in tables if t in state.tables]
        table_objs.sort(key=lambda t: len(t.valid_joins), reverse=True)
        
        for idx, t in enumerate(table_objs):
            # The most connected table is the core entity
            if idx == 0:
                domain_payload["core_tables"].append({
                    "name": t.table_name,
                    "meaning": t.business_meaning or "Unknown",
                    "columns": [f"{c.column_name} ({c.technical_type})" for c in t.columns]
                })
            else:
                domain_payload["satellite_tables"].append({
                    "name": t.table_name,
                    "meaning": t.business_meaning or "Unknown"
                })
                
            # Accumulate joins relevant to this domain
            for join in t.valid_joins:
                if join not in domain_payload["verified_joins"]:
                    domain_payload["verified_joins"].append(join)
                    
        # 3. Inject Enums mapped to these tables
        for enum_list in state.enums.values():
            for enum in enum_list:
                if enum.table_name in tables:
                    enum_key = f"{enum.table_name}.{enum.column_name}"
                    domain_payload["enumerations"][enum_key] = enum.mapping
                    
        artifact["domains"][domain_name] = domain_payload
        
    return artifact
