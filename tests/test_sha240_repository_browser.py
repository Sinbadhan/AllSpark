import copy
from pathlib import Path

from allspark.core.database import Database
from allspark.core.models import (
    KnowledgeEntry,
    compute_risk_classification_hash,
    externalize_knowledge_evidence,
)
from tests.test_sha196_browser import _Chrome, _chrome_binary, _serve
from tests.test_web_ui_v11 import _client

ENTRY_ID = "medical/sha240/unverified"
APPROVED_RISK_ID = "engineering/sha241/approved-risk"
EXTERNAL_RISK_ID = "engineering/sha241/external-risk"


def _risk_review(entry: KnowledgeEntry, hazard: str) -> dict:
    qualification = {
        "fire": "fire_safety",
        "structural": "structural_engineering",
    }[hazard]
    return {
        "signoff_version": 1,
        "reviewer_id": f"reviewer-{hazard}",
        "reviewer": f"Named {hazard} reviewer",
        "qualification_type": qualification,
        "qualification_evidence": f"registry:{qualification}:001",
        "covered_hazards": [hazard],
        "reviewed_at": "2026-07-16",
        "conclusion": "approved",
        "reservations": [],
        "classification_hash": compute_risk_classification_hash(entry),
    }


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
    approved = KnowledgeEntry(
        id=APPROVED_RISK_ID,
        category="engineering",
        subcategory="fire_structure",
        priority=1,
        title="Approved multi-reviewer risk entry",
        summary="Risk review context must precede the action.",
        steps=["Reviewed engineering action."],
        references=[
            {
                "source_id": "fire-authority",
                "title": "Fire authority manual",
                "locator": "Section 4.2",
                "local_status": "verified",
                "verified_by": "local-auditor",
                "verified_at": "2026-07-16",
            },
            {
                "source_id": "structure-authority",
                "title": "Structural safety manual",
                "locator": "Chapter 7",
                "local_status": "verified",
                "verified_by": "local-auditor",
                "verified_at": "2026-07-16",
            },
        ],
        risk_level="high",
        hazards=["fire", "structural"],
        review_status="approved",
        language="en",
    )
    approved.risk_reviews = [
        _risk_review(approved, "fire"),
        _risk_review(approved, "structural"),
    ]
    db.save_knowledge(approved)
    external = copy.deepcopy(approved)
    external.id = EXTERNAL_RISK_ID
    external.title = "External risk-review claim"
    classification_hash = compute_risk_classification_hash(external)
    for review in external.risk_reviews:
        review["classification_hash"] = classification_hash
    externalize_knowledge_evidence(external)
    db.save_knowledge(external)
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
    assert detail["actionable_content"] is False
    assert detail["content_access"] == "withheld_pending_review"
    assert "操作性内容不会展示" in detail["summary"]
    assert detail["applicable_when"] == []
    assert detail["contraindications"] == []
    assert detail["steps"] == []
    assert detail["risk_notice"]
    assert detail["risk_review_status"] == "pending_external_review"
    assert detail["hazards"] == ["unknown"]

    approved = client.get(f"/api/knowledge/{APPROVED_RISK_ID}").json()
    assert approved["risk_review_status"] == "approved"
    assert approved["verification"] == "cross_ref"
    assert approved["risk_notice"] == ""
    assert approved["hazards"] == ["fire", "structural"]
    assert len(approved["risk_reviews"]) == 2
    assert approved["risk_review_claims"] == []
    external = client.get(f"/api/knowledge/{EXTERNAL_RISK_ID}").json()
    assert external["risk_review_status"] == "pending_external_review"
    assert external["risk_reviews"] == []
    assert len(external["risk_review_claims"]) == 2


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
                riskStatus: text.includes('Risk classification pending external review'),
                unknownHazard: text.includes('Hazards not yet classified'),
                applicable: text.includes('Applicable when'),
                contraindications: text.includes('Contraindications'),
                withheld: text.includes('Actionable content is withheld'),
                unsafeStep: text.includes('Act only after checking the warnings.'),
                reference: text.includes('Chapter 3, section 2'),
                externalClaim: text.includes('External, unverified claim'),
                externalReview: text.includes('External expert-review claim'),
                fullHash: text.includes('sha256:' + 'a'.repeat(64)),
                order: [
                  text.indexOf('Actionable content is withheld'),
                  text.indexOf('Risk classification pending external review'),
                  text.indexOf('Hazards not yet classified'),
                  text.indexOf('High-risk guidance'),
                  text.indexOf('Chapter 3, section 2'),
                ],
                closeFocused: document.activeElement?.id === 'repo-detail-close',
              };
            })()"""
        )
        assert state["risk"] and state["riskStatus"] and state["unknownHazard"]
        assert not state["applicable"] and not state["contraindications"]
        assert state["withheld"] and not state["unsafeStep"]
        assert state["reference"] and state["externalClaim"] and state["externalReview"]
        assert state["fullHash"] and state["closeFocused"]
        assert state["order"] == sorted(state["order"])
        browser.evaluate("document.getElementById('repo-detail-close').click()")
        assert browser.evaluate(
            f"document.activeElement?.closest('[data-kid]')?.dataset.kid === '{ENTRY_ID}'"
        )

        for entry_id, title, expected in (
            (
                APPROVED_RISK_ID,
                "Approved multi-reviewer risk entry",
                {
                    "status": "Risk classification externally reviewed",
                    "hazards": ["Fire hazard", "Structural failure"],
                    "local": True,
                    "external": False,
                    "step": "Reviewed engineering action.",
                    "actionable": True,
                },
            ),
            (
                EXTERNAL_RISK_ID,
                "External risk-review claim",
                {
                    "status": "Risk classification pending external review",
                    "hazards": ["Fire hazard", "Structural failure"],
                    "local": False,
                    "external": True,
                    "step": "Reviewed engineering action.",
                    "actionable": False,
                },
            ),
        ):
            browser.evaluate(
                f"_repoFilters.q = {title!r}; _repoRender(); "
                f"(() => {{ const button = document.querySelector('[data-kid=\"{entry_id}\"] .repo-detail-trigger'); button.focus(); button.click(); }})()"
            )
            browser.wait_for("document.querySelector('#repo-detail-modal [role=dialog]') !== null")
            browser.evaluate(
                "document.querySelectorAll('#repo-detail-modal details').forEach(e => e.open = true)"
            )
            risk_state = browser.evaluate(
                f"""(() => {{
                  const dialog = document.querySelector('#repo-detail-modal [role=dialog]');
                  const text = dialog.textContent;
                  const step = {expected['step']!r};
                  const hashes = Array.from(dialog.querySelectorAll('code')).map(e => e.textContent.trim());
                  return {{
                    status: text.includes({expected['status']!r}),
                    hazards: {expected['hazards']!r}.every(value => text.includes(value)),
                    local: text.includes('Local risk-classification review'),
                    external: text.includes('External risk-review claim (not locally trusted)'),
                    naturalQualifications: text.includes('Qualification: Fire safety specialist') && text.includes('Qualification: Structural engineer'),
                    withheld: text.includes('Actionable content is withheld'),
                    stepVisible: text.includes(step),
                    fullHashes: hashes.filter(value => /^sha256:[0-9a-f]{{64}}$/.test(value)).length,
                    visibleHashes: Array.from(dialog.querySelectorAll('details[open] code')).filter(e => e.getClientRects().length > 0 && /^sha256:[0-9a-f]{{64}}$/.test(e.textContent.trim())).length,
                    order: [text.indexOf('Risk classification'), text.indexOf('Potential hazards'), text.indexOf({('Local risk-classification review' if expected['local'] else 'External risk-review claim (not locally trusted)')!r})],
                    closeFocused: document.activeElement?.id === 'repo-detail-close',
                  }};
                }})()"""
            )
            assert risk_state["status"] and risk_state["hazards"]
            assert risk_state["local"] is expected["local"]
            assert risk_state["external"] is expected["external"]
            assert risk_state["naturalQualifications"]
            assert risk_state["withheld"] is (not expected["actionable"])
            assert risk_state["stepVisible"] is expected["actionable"]
            assert risk_state["fullHashes"] == 2
            assert risk_state["visibleHashes"] == 2
            assert risk_state["order"] == sorted(risk_state["order"])
            assert risk_state["closeFocused"]
            browser.evaluate("document.getElementById('repo-detail-close').click()")
            assert browser.evaluate(
                f"document.activeElement?.closest('[data-kid]')?.dataset.kid === '{entry_id}'"
            )

        browser.navigate(f"{base_url}/")
        browser.evaluate(f"showKnowledge('{ENTRY_ID}')", await_promise=True)
        desktop_pending = browser.evaluate(
            """(() => {
              const text = document.querySelector('#knowledge-detail .kb-detail').textContent;
              return {
                status: text.includes('Risk classification pending external review'),
                hazard: text.includes('Hazards not yet classified'),
                withheld: text.includes('Actionable content is withheld'),
                unsafeStep: text.includes('Act only after checking the warnings.'),
                order: [text.indexOf('Actionable content is withheld'), text.indexOf('Risk classification pending external review'), text.indexOf('Hazards not yet classified')],
              };
            })()"""
        )
        assert desktop_pending["status"] and desktop_pending["hazard"]
        assert desktop_pending["withheld"] and not desktop_pending["unsafeStep"]
        assert desktop_pending["order"] == sorted(desktop_pending["order"])
        for entry_id, expected_local, expected_external, expected_actionable in (
            (APPROVED_RISK_ID, True, False, True),
            (EXTERNAL_RISK_ID, False, True, False),
        ):
            browser.evaluate(f"showKnowledge('{entry_id}')", await_promise=True)
            browser.evaluate(
                "document.querySelectorAll('#knowledge-detail details').forEach(e => e.open = true)"
            )
            desktop_qa = browser.evaluate(
                """(() => {
                  const detail = document.querySelector('#knowledge-detail .kb-detail');
                  const text = detail.textContent;
                  const hashes = Array.from(detail.querySelectorAll('details[open] code'));
                  return {
                    fits: document.documentElement.scrollWidth <= innerWidth + 1,
                    local: text.includes('Local risk-classification review'),
                    external: text.includes('External risk-review claim (not locally trusted)'),
                    hazards: text.includes('Fire hazard') && text.includes('Structural failure'),
                    naturalQualifications: text.includes('Qualification: Fire safety specialist') && text.includes('Qualification: Structural engineer'),
                    withheld: text.includes('Actionable content is withheld'),
                    stepVisible: text.includes('Reviewed engineering action.'),
                    visibleHashes: hashes.filter(e => e.getClientRects().length > 0 && /^sha256:[0-9a-f]{64}$/.test(e.textContent.trim())).length,
                    order: [text.indexOf('Risk classification'), text.indexOf('Potential hazards'), text.indexOf(text.includes('Local risk-classification review') ? 'Local risk-classification review' : 'External risk-review claim (not locally trusted)')],
                  };
                })()"""
            )
            assert desktop_qa["fits"] and desktop_qa["hazards"]
            assert desktop_qa["naturalQualifications"]
            assert desktop_qa["local"] is expected_local
            assert desktop_qa["external"] is expected_external
            assert desktop_qa["withheld"] is (not expected_actionable)
            assert desktop_qa["stepVisible"] is expected_actionable
            assert desktop_qa["visibleHashes"] == 2
            assert desktop_qa["order"] == sorted(desktop_qa["order"])

        browser.navigate(f"{base_url}/repository")
        browser.evaluate("initialRepositoryLoad", await_promise=True)
        browser.evaluate("_repoFilters.q = 'Unverified emergency action'; _repoRender()")
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
                riskStatus: dialog.textContent.includes('Risk classification pending external review'),
                unknownHazard: dialog.textContent.includes('Hazards not yet classified'),
                withheld: dialog.textContent.includes('Actionable content is withheld'),
                unsafeStep: dialog.textContent.includes('Act only after checking the warnings.'),
                order: [dialog.textContent.indexOf('Actionable content is withheld'), dialog.textContent.indexOf('Risk classification pending external review'), dialog.textContent.indexOf('Hazards not yet classified')],
              };
            })()"""
        )
        assert fit["page"] and fit["dialog"] and fit["scrollable"] and fit["closeVisible"]
        assert fit["riskStatus"] and fit["unknownHazard"]
        assert fit["withheld"] and not fit["unsafeStep"]
        assert fit["order"] == sorted(fit["order"])
        browser.evaluate("document.getElementById('repo-detail-close').click()")
        assert browser.evaluate(
            f"document.activeElement?.closest('[data-kid]')?.dataset.kid === '{ENTRY_ID}'"
        )

        for entry_id, title in (
            (APPROVED_RISK_ID, "Approved multi-reviewer risk entry"),
            (EXTERNAL_RISK_ID, "External risk-review claim"),
        ):
            browser.evaluate(
                f"_repoFilters.q = {title!r}; _repoRender(); "
                f"document.querySelector('[data-kid=\"{entry_id}\"] .repo-detail-trigger').click()"
            )
            browser.wait_for("document.querySelector('#repo-detail-modal [role=dialog]') !== null")
            browser.evaluate(
                "document.querySelectorAll('#repo-detail-modal details').forEach(e => e.open = true)"
            )
            mobile_risk_fit = browser.evaluate(
                """(() => {
                  const dialog = document.querySelector('#repo-detail-modal [role=dialog]');
                  const codes = Array.from(dialog.querySelectorAll('code'));
                  return {
                    page: document.documentElement.scrollWidth <= innerWidth + 1,
                    dialog: dialog.scrollWidth <= dialog.clientWidth + 1,
                    widths: [dialog.clientWidth, dialog.scrollWidth],
                    offenders: Array.from(dialog.querySelectorAll('*')).filter(e => e.scrollWidth > e.clientWidth + 1).map(e => [e.tagName, e.className, e.clientWidth, e.scrollWidth]).slice(0, 8),
                    fullHashes: codes.filter(e => /^sha256:[0-9a-f]{64}$/.test(e.textContent.trim())).length,
                    visibleHashes: codes.filter(e => e.closest('details')?.open && e.getClientRects().length > 0 && /^sha256:[0-9a-f]{64}$/.test(e.textContent.trim())).length,
                    naturalQualifications: dialog.textContent.includes('Qualification: Fire safety specialist') && dialog.textContent.includes('Qualification: Structural engineer'),
                  };
                })()"""
            )
            assert mobile_risk_fit["page"] is True
            assert mobile_risk_fit["dialog"] is True, mobile_risk_fit
            assert mobile_risk_fit["fullHashes"] == 2
            assert mobile_risk_fit["visibleHashes"] == 2
            assert mobile_risk_fit["naturalQualifications"]
            browser.evaluate("document.getElementById('repo-detail-close').click()")

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
                riskStatus: text.includes('Risk classification pending external review'),
                unknownHazard: text.includes('Hazards not yet classified'),
                withheld: text.includes('Actionable content is withheld'),
                unsafeStep: text.includes('Act only after checking the warnings.'),
                createTask: Boolean(detail.querySelector('[data-index-action="knowledge-task"]')),
                order: [
                  text.indexOf('Actionable content is withheld'),
                  text.indexOf('Risk classification pending external review'),
                  text.indexOf('Hazards not yet classified'),
                  text.indexOf('High-risk guidance'),
                  text.indexOf('Chapter 3, section 2'),
                ],
              };
            })()"""
        )
        assert index_state["fits"] and index_state["externalClaim"]
        assert index_state["externalReview"]
        assert index_state["riskStatus"] and index_state["unknownHazard"]
        assert index_state["withheld"] and not index_state["unsafeStep"]
        assert not index_state["createTask"]
        assert index_state["order"] == sorted(index_state["order"])

        for entry_id, expected_local, expected_external, expected_actionable in (
            (APPROVED_RISK_ID, True, False, True),
            (EXTERNAL_RISK_ID, False, True, False),
        ):
            browser.evaluate(f"showKnowledge('{entry_id}')", await_promise=True)
            browser.evaluate(
                "document.querySelectorAll('#knowledge-detail details').forEach(e => e.open = true)"
            )
            qa_risk = browser.evaluate(
                """(() => {
                  const detail = document.querySelector('#knowledge-detail .kb-detail');
                  const text = detail.textContent;
                  const hashes = Array.from(detail.querySelectorAll('code')).map(e => e.textContent.trim());
                  return {
                    fits: document.documentElement.scrollWidth <= innerWidth + 1,
                    local: text.includes('Local risk-classification review'),
                    external: text.includes('External risk-review claim (not locally trusted)'),
                    hazards: text.includes('Fire hazard') && text.includes('Structural failure'),
                    naturalQualifications: text.includes('Qualification: Fire safety specialist') && text.includes('Qualification: Structural engineer'),
                    withheld: text.includes('Actionable content is withheld'),
                    stepVisible: text.includes('Reviewed engineering action.'),
                    fullHashes: hashes.filter(value => /^sha256:[0-9a-f]{64}$/.test(value)).length,
                    visibleHashes: Array.from(detail.querySelectorAll('details[open] code')).filter(e => e.getClientRects().length > 0 && /^sha256:[0-9a-f]{64}$/.test(e.textContent.trim())).length,
                    order: [text.indexOf('Risk classification'), text.indexOf('Potential hazards'), text.indexOf(text.includes('Local risk-classification review') ? 'Local risk-classification review' : 'External risk-review claim (not locally trusted)')],
                  };
                })()"""
            )
            assert qa_risk["fits"] and qa_risk["hazards"]
            assert qa_risk["naturalQualifications"]
            assert qa_risk["local"] is expected_local
            assert qa_risk["external"] is expected_external
            assert qa_risk["withheld"] is (not expected_actionable)
            assert qa_risk["stepVisible"] is expected_actionable
            assert qa_risk["fullHashes"] == 2
            assert qa_risk["visibleHashes"] == 2
            assert qa_risk["order"] == sorted(qa_risk["order"])
