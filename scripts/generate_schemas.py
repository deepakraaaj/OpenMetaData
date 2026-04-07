import json
import os
from pathlib import Path

from app.models.state import (
    KnowledgeState,
    ReadinessState,
    SemanticGap,
    GapCategory
)
from app.models.semantic import (
    SemanticTable,
    SemanticColumn,
    SensitivityLabel
)
from app.models.source_attribution import (
    SourceAttribution,
    DiscoverySource
)
from app.models.common import NamedConfidence, ConfidenceLabel

def main():
    base_dir = Path(__file__).parent.parent
    output_dir = base_dir / "output"
    output_dir.mkdir(exist_ok=True)

    # 1. Generate JSON Schema
    schema = KnowledgeState.model_json_schema()
    schema_path = output_dir / "schema_knowledge_state.json"
    with open(schema_path, "w") as f:
        json.dump(schema, f, indent=2)
    print(f"Schema written to {schema_path}")

    # 2. Build example state
    attribution_db = SourceAttribution(
        source=DiscoverySource.PULLED_FROM_DB_SCHEMA,
        tooling_notes="Discovered via SQLAlchemy inspector"
    )
    
    attribution_user = SourceAttribution(
        source=DiscoverySource.CONFIRMED_BY_USER,
        user="admin@example.com",
        timestamp="2026-04-07T12:00:00Z"
    )

    example_state = KnowledgeState(
        tables={
            "users": SemanticTable(
                table_name="users",
                business_meaning="Registered users of the platform",
                columns=[
                    SemanticColumn(
                        column_name="id",
                        technical_type="INTEGER",
                        attribution=attribution_db
                    ),
                    SemanticColumn(
                        column_name="email",
                        technical_type="VARCHAR",
                        sensitive=SensitivityLabel.sensitive,
                        confidence=NamedConfidence(label=ConfidenceLabel.high, score=0.9),
                        attribution=attribution_user
                    )
                ],
                attribution=attribution_db
            )
        },
        unresolved_gaps=[
            SemanticGap(
                gap_id="gap-users-pk",
                category=GapCategory.MISSING_PRIMARY_KEY,
                target_entity="users",
                description="Database schema does not define a primary key for 'users'.",
                suggested_question="Which column uniquely identifies a user?",
                is_blocking=True
            )
        ],
        readiness=ReadinessState(
            is_ready=False,
            readiness_percentage=50.0,
            blocking_gaps_count=1,
            total_gaps_count=1,
            readiness_notes=["Missing primary key on core entity 'users'."]
        )
    )

    example_path = output_dir / "example_state.json"
    with open(example_path, "w") as f:
        f.write(example_state.model_dump_json(indent=2))
    
    print(f"Example state written to {example_path}")

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    main()
