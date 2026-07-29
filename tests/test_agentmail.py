import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "store"))

import agentmail  # noqa: E402
import issue_license  # noqa: E402


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def test_build_license_payload_base64_encodes_only_attachment(tmp_path):
    license_file = tmp_path / "license.key"
    license_file.write_text("LICENSED_TO=buyer@example.com\nLICENSE_ID=ABC123\n", encoding="utf-8")

    payload = agentmail.build_license_payload(
        buyer_email="Buyer@Example.com",
        subject="PlugICT license",
        text="plain body",
        html="<p>html body</p>",
        license_path=license_file,
        bcc="support@plugict.com",
        reply_to="support@plugict.com",
    )

    assert payload["to"] == ["buyer@example.com"]
    assert payload["bcc"] == ["support@plugict.com"]
    assert payload["reply_to"] == ["support@plugict.com"]
    assert payload["attachments"][0]["filename"] == "license.key"
    assert base64.b64decode(payload["attachments"][0]["content"]) == license_file.read_bytes()
    assert "LICENSE_ID=ABC123" not in json.dumps({k: v for k, v in payload.items() if k != "attachments"})


def test_send_message_uses_official_endpoint_and_returns_ids(tmp_path):
    license_file = tmp_path / "license.key"
    license_file.write_bytes(b"test-license")
    payload = agentmail.build_license_payload(
        buyer_email="buyer@example.com",
        subject="PlugICT license",
        text="body",
        html="<p>body</p>",
        license_path=license_file,
    )
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse('{"message_id":"msg_test_1","thread_id":"thread_test_1"}')

    result = agentmail.send_message(
        inbox_id="orders-test@agentmail.to",
        payload=payload,
        api_key="test-only-key",
        opener=opener,
    )

    assert captured["url"].endswith("/v0/inboxes/orders-test%40agentmail.to/messages/send")
    assert captured["auth"] == "Bearer test-only-key"
    assert captured["body"]["to"] == ["buyer@example.com"]
    assert result == {
        "provider": "agentmail",
        "status": "sent",
        "message_id": "msg_test_1",
        "thread_id": "thread_test_1",
    }


def test_missing_agentmail_config_fails_closed(tmp_path):
    license_file = tmp_path / "license.key"
    license_file.write_text("key", encoding="utf-8")
    payload = agentmail.build_license_payload(
        buyer_email="buyer@example.com",
        subject="subject",
        text="text",
        html="<p>text</p>",
        license_path=license_file,
    )

    with pytest.raises(agentmail.AgentMailError, match="AGENTMAIL_API_KEY"):
        agentmail.send_message(inbox_id="orders-test@agentmail.to", payload=payload, api_key="")


def test_http_error_does_not_echo_api_key():
    def opener(request, timeout):
        error = HTTPError(request.full_url, 401, "unauthorized", {}, None)
        error.read = lambda: b"bad credentials"
        raise error

    with pytest.raises(agentmail.AgentMailError, match="AgentMail HTTP 401") as exc:
        agentmail.send_message(
            inbox_id="orders-test@agentmail.to",
            payload={"to": ["buyer@example.com"]},
            api_key="secret-that-must-not-leak",
            opener=opener,
        )
    assert "secret-that-must-not-leak" not in str(exc.value)


def test_issue_license_selects_agentmail_provider(tmp_path, monkeypatch):
    license_file = tmp_path / "license.key"
    license_file.write_text("key", encoding="utf-8")
    captured = {}

    def fake_send_license(**kwargs):
        captured.update(kwargs)
        return {"provider": "agentmail", "status": "sent", "message_id": "m1", "thread_id": "t1"}

    monkeypatch.setenv("PLUGICT_EMAIL_PROVIDER", "agentmail")
    monkeypatch.setenv("AGENTMAIL_REPLY_TO", "support@plugict.com")
    monkeypatch.setattr(issue_license.agentmail, "send_license", fake_send_license)

    result = issue_license._email_license("buyer@example.com", license_file, "LIC-1")

    assert result["message_id"] == "m1"
    assert captured["buyer_email"] == "buyer@example.com"
    assert captured["license_path"] == license_file
    assert captured["reply_to"] == "support@plugict.com"


def test_ledger_records_agentmail_delivery_metadata(tmp_path, monkeypatch):
    ledger = tmp_path / "issued_licenses.csv"
    monkeypatch.setattr(issue_license, "LEDGER", ledger)

    issue_license._log(
        "buyer@example.com",
        "ORDER-1",
        "LIC-1",
        "license_buyer.key",
        "stripe",
        {"provider": "agentmail", "message_id": "m1", "thread_id": "t1", "status": "sent"},
    )

    text = ledger.read_text(encoding="utf-8")
    assert "email_provider" in text
    assert "agentmail" in text
    assert "m1" in text and "t1" in text and "sent" in text
