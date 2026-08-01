"""Write buyer AI-agent configs with this installation's exact runtime paths.

Safe to re-run after moving the folder. Paths use forward slashes so generated
YAML cannot be broken by Windows backslash escapes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = Path(__file__).resolve().parent
VENV_PY = ROOT / (".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python")
SERVER = ROOT / "mcp_server.py"
TEMP_DIR = ROOT / ".tmp"
HF_HOME = ROOT / ".hf-home"


def env_config() -> dict[str, str]:
    return {
        "ICT_TEMP_DIR": TEMP_DIR.resolve().as_posix(),
        "HF_HOME": HF_HOME.resolve().as_posix(),
        "PYTHONNOUSERSITE": "1",
    }


def json_config() -> str:
    cfg = {
        "mcpServers": {
            "plugict": {
                "command": VENV_PY.resolve().as_posix(),
                "args": ["-E", "-X", "utf8", SERVER.resolve().as_posix()],
                "env": env_config(),
            }
        }
    }
    return json.dumps(cfg, indent=2) + "\n"


def hermes_config() -> str:
    env = env_config()
    lines = [
        "# Add this block under mcp_servers in your Hermes profile config.yaml",
        "mcp_servers:",
        "  plugict:",
        f'    command: "{VENV_PY.resolve().as_posix()}"',
        f'    args: ["-E", "-X", "utf8", "{SERVER.resolve().as_posix()}"]',
        "    enabled: true",
        "    connect_timeout: 180",
        "    env:",
    ]
    lines.extend(f'      {key}: "{value}"' for key, value in env.items())
    return "\n".join(lines) + "\n"


(EXAMPLES / "claude_desktop_config.json").write_text(json_config(), encoding="utf-8")
(EXAMPLES / "cursor_mcp.json").write_text(json_config(), encoding="utf-8")
(EXAMPLES / "hermes_config.yaml").write_text(hermes_config(), encoding="utf-8")
print(f"AI-agent configs written for: {ROOT}")
