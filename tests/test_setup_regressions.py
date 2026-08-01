import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("plugict_setup", ROOT / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def write_license(path: Path, **overrides):
    fields = {
        "LICENSED_TO": "buyer@example.com",
        "PURCHASE_ID": "ORDER-123",
        "LICENSE_ID": "ABC123",
        "ISSUED": "2026-08-01",
        "BUYER_KEY": "valid-buyer-key",
        "ENCRYPTED_VAULT_KEY": "wrapped-key",
        "VAULT_HASH": "a" * 64,
    }
    fields.update(overrides)
    path.write_text(
        "# PlugICT license envelope\n"
        + "\n".join(f"{key}={value}" for key, value in fields.items())
        + "\n",
        encoding="utf-8",
    )


def test_license_validation_rejects_id_only_input(tmp_path):
    path = tmp_path / "license.key"
    path.write_text("184EE631A2D0229B\n", encoding="utf-8")

    with pytest.raises(setup.LicenseError, match="full license.key envelope"):
        setup.read_license(path)


def test_license_validation_accepts_full_envelope(tmp_path):
    path = tmp_path / "license.key"
    write_license(path)

    fields = setup.read_license(path)

    assert fields["LICENSED_TO"] == "buyer@example.com"
    assert fields["LICENSE_ID"] == "ABC123"


def test_doctor_failure_is_fatal(monkeypatch, tmp_path):
    runtime = tmp_path / "python"
    runtime.write_text("placeholder", encoding="utf-8")
    doctor = tmp_path / "mcp_server.py"
    doctor.write_text("# fixture", encoding="utf-8")
    (tmp_path / "vault_core.py").write_text("# fixture", encoding="utf-8")
    (tmp_path / "ict-vault.kevin").write_bytes(b"fixture")
    (tmp_path / "license.key").write_text("fixture", encoding="utf-8")
    (tmp_path / "smoke_test.py").write_text("# fixture", encoding="utf-8")
    monkeypatch.setattr(setup, "HERE", tmp_path)
    monkeypatch.setattr(setup, "runtime_python", lambda: runtime)
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Result", (), {"returncode": 1, "stdout": "doctor failed", "stderr": "missing mcp"}
        )(),
    )

    with pytest.raises(setup.SetupError, match="doctor failed"):
        setup.verify_installation()


def test_hermes_config_is_valid_and_has_cold_start_safety(tmp_path):
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    server = tmp_path / "mcp_server.py"

    rendered = setup.render_hermes_config(python, server, tmp_path / ".tmp", tmp_path / ".hf-home")
    parsed = yaml.safe_load(rendered)

    plugict = parsed["mcp_servers"]["plugict"]
    assert plugict["connect_timeout"] >= 120
    assert plugict["args"][:3] == ["-E", "-X", "utf8"]
    assert "ICT_TEMP_DIR" in plugict["env"]
    assert "\\PlugICT\\" not in rendered


def test_json_config_uses_same_runtime_and_server(tmp_path):
    python = tmp_path / ".venv" / "bin" / "python"
    server = tmp_path / "mcp_server.py"

    parsed = json.loads(setup.render_json_config(python, server, tmp_path / ".tmp", tmp_path / ".hf-home"))
    server_cfg = parsed["mcpServers"]["plugict"]

    assert server_cfg["command"] == python.as_posix()
    assert server_cfg["args"] == ["-E", "-X", "utf8", server.as_posix()]
    assert server_cfg["env"]["ICT_TEMP_DIR"] == (tmp_path / ".tmp").as_posix()
