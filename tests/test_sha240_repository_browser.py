from pathlib import Path

from allspark.core.database import Database
from allspark.core.models import KnowledgeEntry
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client

ENTRY_ID = "medical/sha240/unverified"


def _seed(path: Path) -> None:
    db = Database(path)
    db.save_knowledge(KnowledgeEntry(
        id=ENTRY_ID,
        category="medical",
        subcategory="first_aid",
        priority=0,
        title="Unverified emergency action",
        summary="Use only after checking the stated evidence boundary.",
        steps=["Act only after checking the warnings."],
        warnings=["Do not delay emergency services."],
        source="other_spark",
        source_claim="pre_collapse",
        verification_claim="field_tested",
        references=[{
            "source_id": "external-manual",
            "title": "External manual claim",
            "locator": "Chapter 3, section 2",
            "local_status": "external_claim",
        }],
        field_records=[{
            "record_id": "external-record",
            "source_id": "external-team",
            "conditions": ["claimed condition"],
            "outcome": "Claimed field outcome",
            "recorded_at": "2026-07-15",
            "locator": "external-log:1",
            "local_status": "external_claim",
        }],
        review_claim={
            "reviewer": "External Reviewer",
            "qualification": "Claimed emergency credential",
            "review_date": "2026-07-15",
            "citation": "External manual, section 9",
            "content_hash": "sha256:" + "a" * 64,
            "signoff_version": 3,
            "local_status": "external_claim",
        },
        applicable_when=["Only when the described condition is present"],
        contraindications=["When trained emergency help is immediately available"],
        language="en",
    ))
    db.close()


def test_repository_api_summary_and_detail_contract(tmp_path: Path) -> None:
    path = tmp_path / "api.db"
    _seed(path)
    client = _client(str(path))
    client.post("/api/system/language", json={"language": "zh"})
    summaries = client.get("/api/knowledge/category/medical").json()
    summary = next(item for item in summaries if item["id"] == ENTRY_ID)
    assert summary["verification"] == "unverified"
    assert summary["verification_label"] == "未验证"
    assert summary["evidence_counts"] == {
        "verified_references": 0,
        "verified_field_records": 0,
        "external_reference_claims": 1,
        "external_field_claims": 1,
        "local_expert_reviews": 0,
        "external_review_claims": 1,
    }
    for private_field in (
        "references", "field_records", "applicable_when", "contraindications",
    ):
        assert private_field not in summary

    detail = client.get(f"/api/knowledge/{ENTRY_ID}").json()
    assert detail["references"][0]["locator"] == "Chapter 3, section 2"
    assert detail["references"][0]["trust_status"] == "external_claim"
    assert detail["references"][0]["trust_label"] == "外部提供、尚未验证的声称"
    assert detail["field_records"][0]["trust_status"] == "external_claim"
    assert detail["external_review_claim"]["reviewer"] == "External Reviewer"
    assert detail["external_review_claim"]["trust_status"] == "external_claim"
    assert detail["applicable_when"]
    assert detail["contraindications"]
    assert detail["risk_notice"]


def test_repository_chrome_truth_order_filter_and_mobile_fit(tmp_path: Path, request) -> None:
    path = tmp_path / "browser.db"
    _seed(path)
    client = _client(str(path))
    client.post("/api/system/language", json={"language": "en"})
    request.addfinalizer(
        lambda: client.post("/api/system/language", json={"language": "zh"})
    )
    with _serve(client.app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-profile"
    ) as browser:
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 720, "deviceScaleFactor": 1, "mobile": False},
        )
        browser.navigate(f"{base_url}/repository")
        browser.evaluate("initialRepositoryLoad", await_promise=True)
        options = browser.evaluate(
            "Array.from(document.querySelectorAll('#repo-f-ver option')).map(o => ({value:o.value,label:o.textContent.trim()}))"
        )
        unverified = next(option for option in options if option["value"] == "unverified")
        assert unverified["label"] == "Unverified"
        assert all(option["label"] != "unverified" for option in options)

        browser.evaluate("_repoFilters.q = 'Unverified emergency action'; _repoRender()")
        browser.evaluate(
            f"(() => {{ const row = document.querySelector('[data-kid=\"{ENTRY_ID}\"]'); "
            "const button = row.querySelector('.repo-detail-trigger'); button.focus(); button.click(); })()"
        )
        browser.wait_for("document.querySelector('#repo-detail-modal [role=dialog]') !== null")
        state = browser.evaluate(
            """(() => {
              const dialog = document.querySelector('#repo-detail-modal [role=dialog]');
              const text = dialog.textContent;
              return {
                risk: text.includes('High-risk guidance'),
                applicable: text.includes('Applicable when'),
                contraindications: text.includes('Contraindications'),
                reference: text.includes('Chapter 3, section 2'),
                externalClaim: text.includes('External, unverified claim'),
                externalReview: text.includes('External expert-review claim'),
                fullHash: text.includes('sha256:' + 'a'.repeat(64)),
                order: [
                  text.indexOf('High-risk guidance'),
                  text.indexOf('Applicable when'),
                  text.indexOf('Contraindications'),
                  text.indexOf('Chapter 3, section 2'),
                  text.indexOf('Act only after checking the warnings.'),
                ],
                closeFocused: document.activeElement?.id === 'repo-detail-close',
              };
            })()"""
        )
        assert state["risk"] and state["applicable"] and state["contraindications"]
        assert state["reference"] and state["externalClaim"] and state["externalReview"]
        assert state["fullHash"] and state["closeFocused"]
        assert state["order"] == sorted(state["order"])
        browser.evaluate("document.getElementById('repo-detail-close').click()")
        assert browser.evaluate(
            f"document.activeElement?.closest('[data-kid]')?.dataset.kid === '{ENTRY_ID}'"
        )

        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 320, "height": 568, "deviceScaleFactor": 1, "mobile": True},
        )
        mobile_status = browser.evaluate(
            "document.querySelector('.repo-mobile-item [data-meta=verification]')?.textContent.trim()"
        )
        assert mobile_status == "High risk · Unverified"
        browser.evaluate(
            "(() => { const button = document.querySelector('.repo-mobile-item .repo-detail-trigger'); "
            "button.focus(); button.click(); })()"
        )
        browser.wait_for("document.querySelector('#repo-detail-modal [role=dialog]') !== null")
        fit = browser.evaluate(
            """(() => {
              const dialog = document.querySelector('#repo-detail-modal [role=dialog]');
              return {
                page: document.documentElement.scrollWidth <= innerWidth + 1,
                dialog: dialog.getBoundingClientRect().width <= innerWidth,
                scrollable: dialog.scrollHeight >= dialog.clientHeight,
                closeVisible: !!document.getElementById('repo-detail-close'),
              };
            })()"""
        )
        assert fit == {"page": True, "dialog": True, "scrollable": True, "closeVisible": True}
        browser.evaluate("document.getElementById('repo-detail-close').click()")
        assert browser.evaluate(
            f"document.activeElement?.closest('[data-kid]')?.dataset.kid === '{ENTRY_ID}'"
        )

        browser.navigate(f"{base_url}/")
        browser.evaluate(
            "document.getElementById('knowledge-search').value = 'Unverified emergency action'; searchKnowledge()",
            await_promise=True,
        )
        browser.evaluate(f"showKnowledge('{ENTRY_ID}')", await_promise=True)
        index_state = browser.evaluate(
            """(() => {
              const detail = document.querySelector('#knowledge-detail .kb-detail');
              const text = detail.textContent;
              return {
                fits: document.documentElement.scrollWidth <= innerWidth + 1,
                externalClaim: text.includes('External, unverified claim'),
                externalReview: text.includes('External expert-review claim'),
                order: [
                  text.indexOf('High-risk guidance'),
                  text.indexOf('Applicable when'),
                  text.indexOf('Contraindications'),
                  text.indexOf('Chapter 3, section 2'),
                  text.indexOf('Act only after checking the warnings.'),
                ],
              };
            })()"""
        )
        assert index_state["fits"] and index_state["externalClaim"]
        assert index_state["externalReview"]
        assert index_state["order"] == sorted(index_state["order"])
