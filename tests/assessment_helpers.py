"""Shared valid SHA-238 first-run payloads for cross-cutting tests."""

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
