"""Shared valid SHA-238 first-run payloads for cross-cutting tests."""

from copy import deepcopy
from typing import Any

from allspark.core.models import ResourceType


def valid_initial_assessment(*, confirmed: bool = True) -> dict:
    return {
        "people_count": {"status": "known", "value": 1},
        "health": {"status": "known", "value": "healthy"},
        "urgency": {"status": "known", "value": "stable"},
        "shelter": {"status": "known", "value": "permanent_building"},
        "threats": {"status": "none", "values": []},
        "resources": {
            resource.value: {
                "status": "known",
                "amount": 10,
                "rates": {"status": "unknown"},
            }
            for resource in ResourceType
        },
        "confirmed": confirmed,
    }


def confirmed_init_payload(
    client: Any,
    *,
    assessment: dict | None = None,
    language: str = "en",
    **extra: Any,
) -> dict:
    """Build a Web init request from the server's deterministic preview."""
    assessment = deepcopy(assessment or valid_initial_assessment())
    preview = client.post(
        "/api/init/assessment/preview",
        json={"language": language, "assessment": assessment},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assessment["as_of"] = body["summary"]["as_of"]
    assessment["confirmed"] = True
    return {
        "language": language,
        "assessment": assessment,
        "plan_id": body["plan"]["id"],
        "primary_action_id": body["plan"]["primary_candidate_ids"][0],
        **extra,
    }
