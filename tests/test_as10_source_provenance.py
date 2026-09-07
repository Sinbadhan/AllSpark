"""Source attribution is not permission to mark clinical guidance approved."""
from allspark.core.i18n import MESSAGES
from allspark.services.immediate_danger import load_action_catalog


def test_redirected_first_aid_source_names_actual_publisher():
    catalog = load_action_catalog()
    source = catalog["sources"]["nhs-first-aid"]  # Historical stable key only.
    assert source["organization"] == "St John Ambulance"
    assert source["url"] == "https://www.sja.org.uk/first-aid-advice/"
    assert source["retrieved_at"] == "2026-09-07"
    for lang in ("zh", "en"):
        assert "St John Ambulance" in MESSAGES[lang][source["locator_key"]]
    assert catalog["reviewer_signoffs"] == []
    assert catalog["release_eligible"] is False


def test_poison_source_ids_distinguish_exposure_help_and_no_vomiting_claim():
    catalog = load_action_catalog()
    action = next(row for row in catalog["actions"] if row["action_id"] == "stop-poison-exposure")
    assert action["source_ids"] == ["hrsa-poison-help", "ncpc-poison-first-aid"]
    hrsa = catalog["sources"]["hrsa-poison-help"]
    poison_center = catalog["sources"]["ncpc-poison-first-aid"]
    assert "vomiting" not in hrsa["assertion"].lower()
    assert "do not induce vomiting" in poison_center["assertion"].lower()
    assert poison_center["url"] == "https://www.poison.org/first-aid-for-poisonings"
    assert action["review_status"] == "pending_external_review"
