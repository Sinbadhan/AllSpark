from __future__ import annotations

import time
from pathlib import Path

from allspark.adapters import web_ui
from allspark.adapters.web_ui import create_app
from tests.test_sha196_browser import _Chrome, _chrome_binary
from tests.test_sha221_init_browser import _serve_init


def _press(browser: _Chrome, key: str, code: str, virtual_key: int) -> None:
    browser.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyDown",
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": virtual_key,
        },
    )
    browser.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyUp",
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": virtual_key,
        },
    )


def test_immediate_danger_flow_is_action_first_ephemeral_and_accessible(
    monkeypatch, tmp_path: Path
) -> None:
    detector_calls: list[float] = []
    real_detector = web_ui.detect_hardware

    def counted_detector():
        detector_calls.append(time.monotonic())
        return real_detector()

    monkeypatch.setattr(web_ui, "detect_hardware", counted_detector)
    app = create_app(str(tmp_path / "immediate-danger-browser.db"))
    with _serve_init(app) as base_url, _Chrome(
        _chrome_binary(), tmp_path / "chrome-danger-profile"
    ) as browser:
        browser.call("Emulation.setLocaleOverride", {"locale": "en-US"})
        browser.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'language', "
                "{get: () => 'en-US'});"
            },
        )
        browser.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 320, "height": 568, "deviceScaleFactor": 1, "mobile": True},
        )
        browser.navigate(base_url)
        browser.wait_for("document.getElementById('immediate-danger-open').offsetParent !== null")
        assert detector_calls == []
        assert browser.evaluate(
            "document.getElementById('immediate-danger-open').textContent.trim()"
        ) == "Immediate danger"

        browser.evaluate("document.getElementById('btn-step1-next').click()")
        browser.wait_for("!document.getElementById('step-2').classList.contains('hidden')")
        browser.evaluate("document.getElementById('immediate-danger-open').click()")
        browser.wait_for("document.getElementById('danger-question-title') !== null")
        initial = browser.evaluate(
            "({field:document.querySelector('[data-action=danger-choice]').dataset.field,"
            "active:document.activeElement.id,inert:document.querySelector('main').inert,"
            "options:Array.from(document.querySelectorAll('[data-action=danger-choice]')).map(x=>x.dataset.value)})"
        )
        assert initial == {
            "field": "threat_type",
            "active": "danger-question-title",
            "inert": True,
            "options": [
                "fire_smoke_or_co",
                "severe_bleeding",
                "medical",
                "other",
                "none",
                "unknown",
            ],
        }

        # The last control wraps to the first control inside the modal.
        browser.evaluate(
            "document.querySelector('.danger-actions button:last-child').focus()"
        )
        _press(browser, "Tab", "Tab", 9)
        assert browser.evaluate("document.activeElement.id") == "immediate-danger-close"

        # Delay one old response, close, and reopen. The stale response must
        # never replace the new flow's first question.
        browser.evaluate(
            """(() => {
              const realFetch = window.fetch.bind(window);
              window.fetch = (url, options={}) => {
                if (String(url).includes('/api/immediate-danger/assess')) {
                  const facts = JSON.parse(options.body || '{}').facts || {};
                  if (facts.threat_type === 'severe_bleeding' && !facts.scene_safe) {
                    return new Promise(resolve => setTimeout(
                      () => resolve(realFetch(url, options)), 300));
                  }
                }
                return realFetch(url, options);
              };
            })()"""
        )
        locked = browser.evaluate(
            """(() => {
              document.querySelector('[data-value=severe_bleeding]').click();
              return {
                allDisabled:Array.from(document.querySelectorAll(
                  '[data-action=danger-choice][data-field=threat_type]'
                )).every(button=>button.disabled),
                backDisabled:document.getElementById('immediate-danger-back').disabled
              };
            })()"""
        )
        assert locked == {"allDisabled": True, "backDisabled": True}
        browser.evaluate("closeDanger();openDanger(document.getElementById('immediate-danger-open'))")
        browser.wait_for(
            "document.querySelector('[data-action=danger-choice][data-field=threat_type]') !== null"
        )
        time.sleep(0.45)
        assert browser.evaluate(
            "document.querySelector('.danger-action') === null && "
            "document.querySelector('[data-field=threat_type]') !== null"
        ) is True

        browser.evaluate(
            "document.querySelector('[data-value=severe_bleeding]').click()"
        )
        browser.wait_for(
            "document.querySelector('[data-action=danger-choice][data-field=scene_safe]') !== null"
        )
        browser.evaluate(
            "document.querySelector('[data-field=scene_safe][data-value=yes]').click()"
        )
        browser.wait_for("document.querySelector('.danger-action') !== null")
        action = browser.evaluate(
            """(() => {
              const wrapper=document.querySelector('.danger-action');
              const text=wrapper.querySelector('.danger-action-text');
              const communication=wrapper.querySelector('#danger-communication');
              const boundary=wrapper.querySelector('.danger-review');
              const details=wrapper.querySelector('details');
              return {id:wrapper.dataset.actionId,active:document.activeElement.id,
                text:text.textContent,detailsOpen:details.open,
                order:text.compareDocumentPosition(communication)&Node.DOCUMENT_POSITION_FOLLOWING
                  &&communication.compareDocumentPosition(boundary)&Node.DOCUMENT_POSITION_FOLLOWING
                  &&boundary.compareDocumentPosition(details)&Node.DOCUMENT_POSITION_FOLLOWING,
                raw:wrapper.textContent.includes('immediate_danger_'),
                overflow:document.documentElement.scrollWidth>window.innerWidth};
            })()"""
        )
        assert action == {
            "id": "apply-direct-pressure",
            "active": "danger-action-title",
            "text": "Apply firm, continuous direct pressure to the life-threatening external bleeding now.",
            "detailsOpen": False,
            "order": 4,
            "raw": False,
            "overflow": False,
        }

        browser.evaluate(
            "document.querySelector('[data-field=communication][data-value=unavailable]').click()"
        )
        browser.wait_for("document.getElementById('danger-communication-selected') !== null")
        selected = browser.evaluate(
            "({text:document.getElementById('danger-communication-selected').textContent,"
            "hasClaim:document.querySelector('.danger-action').textContent.includes('has contacted')})"
        )
        assert selected == {"text": "Communication: Unavailable", "hasClaim": False}

        browser.evaluate("document.querySelector('.danger-action details').open=true")
        expanded = browser.evaluate(
            "({open:document.querySelector('.danger-action details').open,"
            "source:document.querySelector('.danger-source').textContent,"
            "escalation:Array.from(document.querySelectorAll('.danger-evidence h4')).map(x=>x.textContent),"
            "overflow:document.querySelector('.danger-dialog-card').scrollWidth>"
            "document.querySelector('.danger-dialog-card').clientWidth})"
        )
        assert expanded["open"] is True
        assert "American Red Cross" in expanded["source"]
        assert "Escalation" in expanded["escalation"]
        assert expanded["overflow"] is False

        browser.evaluate("selectLanguage('zh')")
        browser.wait_for(
            "document.querySelector('.danger-action-text')?.textContent.includes('直接加压')"
        )
        switched = browser.evaluate(
            "({id:document.querySelector('.danger-action').dataset.actionId,"
            "communication:document.getElementById('danger-communication-selected').textContent,"
            "raw:document.querySelector('.danger-action').textContent.includes('immediate_danger_')})"
        )
        assert switched == {
            "id": "apply-direct-pressure",
            "communication": "通信：无法通信",
            "raw": False,
        }

        # Back removes one fact and clears the old action DOM.
        browser.evaluate("document.getElementById('immediate-danger-back').click()")
        browser.wait_for(
            "document.querySelector('[data-field=communication]') !== null && "
            "document.getElementById('danger-communication-selected') === null"
        )
        browser.evaluate("document.getElementById('immediate-danger-back').click()")
        browser.wait_for(
            "document.querySelector('[data-field=scene_safe]') !== null && "
            "document.querySelector('.danger-action') === null"
        )
        _press(browser, "Escape", "Escape", 27)
        browser.wait_for(
            "document.getElementById('immediate-danger-dialog').classList.contains('hidden')"
        )
        closed = browser.evaluate(
            "({focus:document.activeElement.id,step2:!document.getElementById('step-2').classList.contains('hidden'),"
            "inert:document.querySelector('main').inert})"
        )
        assert closed == {"focus": "immediate-danger-open", "step2": True, "inert": False}

        browser.navigate(base_url)
        browser.wait_for("!document.getElementById('step-1').classList.contains('hidden')")
        restarted = browser.evaluate(
            "fetch('/api/init/status').then(r=>r.json()).then(x=>({initialized:x.initialized,"
            "dialogHidden:document.getElementById('immediate-danger-dialog').classList.contains('hidden'),"
            "entryVisible:document.getElementById('immediate-danger-open').offsetParent!==null}))",
            await_promise=True,
        )
        assert restarted == {
            "initialized": False,
            "dialogHidden": True,
            "entryVisible": True,
        }
        assert detector_calls == []

        browser.evaluate(
            "showStep(4);document.getElementById('hardware-details').open=true"
        )
        for _ in range(100):
            if detector_calls:
                break
            time.sleep(0.02)
        assert len(detector_calls) == 1
        browser.evaluate(
            "document.getElementById('hardware-details').open=false;"
            "document.getElementById('hardware-details').open=true"
        )
        time.sleep(0.1)
        assert len(detector_calls) == 1
