#!/usr/bin/env python3
"""PlugICT — one-command buyer setup.

The installer is deliberately fail-closed: it accepts only a complete license
file, installs dependencies into a buyer-local virtual environment, runs the
real doctor check, performs an MCP search smoke test, and only then reports
success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "godzillacode0000/plugICT"
ASSET_NAME = "plugict.zip"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
FALLBACK_URL = f"https://github.com/{REPO}/releases/latest/download/{ASSET_NAME}"
HERE = Path(__file__).parent.resolve()
RUNTIME_FILES = (
    "mcp_server.py",
    "plugict_search.py",
    "vault_core.py",
    "ict-vault.kevin",
    "license.key",
    "smoke_test.py",
)
CONFIG_CONNECT_TIMEOUT = 180


class SetupError(RuntimeError):
    """A buyer setup step failed and setup must not claim success."""


class LicenseError(SetupError):
    """The supplied file is not a complete PlugICT license envelope."""


def runtime_python() -> Path:
    """Return the interpreter dedicated to this buyer installation."""
    if sys.platform == "win32":
        return HERE / ".venv" / "Scripts" / "python.exe"
    return HERE / ".venv" / "bin" / "python"


def runtime_dirs() -> dict[str, Path]:
    return {
        "temp": HERE / ".tmp",
        "hf_home": HERE / ".hf-home",
        "pip_cache": HERE / ".pip-cache",
    }


def child_env() -> dict[str, str]:
    """Build a clean environment for the buyer runtime.

    In particular, do not allow the host agent's PYTHONPATH/PYTHONHOME to
    contaminate the buyer venv. Heavy temporary/model files stay beside the
    installation instead of silently filling a small system drive.
    """
    dirs = runtime_dirs()
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "ICT_TEMP_DIR": str(dirs["temp"]),
            "HF_HOME": str(dirs["hf_home"]),
            "PIP_CACHE_DIR": str(dirs["pip_cache"]),
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    return env


def step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def prompt(msg: str) -> str:
    return input(f"\n{msg}: ").strip().strip('"')


def check_python() -> None:
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        raise SetupError(f"Python 3.10+ required. You have {v.major}.{v.minor}.{v.micro}")
    print(f"  Python {v.major}.{v.minor}.{v.micro} — OK")


def create_runtime_environment() -> None:
    """Create the buyer-local virtual environment; never use global pip."""
    python = runtime_python()
    if python.exists():
        print(f"  Isolated environment present: {python}")
        return
    subprocess.check_call([sys.executable, "-m", "venv", str(HERE / ".venv")])
    if not python.exists():
        raise SetupError("Could not create the buyer-local .venv.")
    print("  Isolated environment created")


def install_deps() -> None:
    req = HERE / "requirements.txt"
    if not req.exists():
        raise SetupError("requirements.txt is missing from the PlugICT package.")
    python = runtime_python()
    subprocess.check_call([str(python), "-E", "-X", "utf8", "-m", "pip", "install", "-q", "-r", str(req)])
    print("  Dependencies installed into buyer .venv")


def _parse_key_value_file(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise LicenseError("The license file is not valid UTF-8 text.") from exc
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def read_license(path: Path) -> dict[str, str]:
    """Read and validate a complete license envelope without exposing secrets."""
    path = Path(path).expanduser()
    if not path.exists() or not path.is_file():
        raise LicenseError(
            "License input must be the path to the full license.key envelope; file not found. "
            "Do not paste LICENSE_ID or PURCHASE_ID."
        )
    fields = _parse_key_value_file(path)
    required = {
        "LICENSED_TO",
        "PURCHASE_ID",
        "LICENSE_ID",
        "BUYER_KEY",
        "ENCRYPTED_VAULT_KEY",
        "VAULT_HASH",
    }
    missing = sorted(key for key in required if not fields.get(key))
    if missing:
        raise LicenseError(
            "This is not a full license.key envelope. "
            f"Missing fields: {', '.join(missing)}. "
            "Use the license.key file from the purchase email; do not paste an ID."
        )
    vault_hash = fields["VAULT_HASH"].lower()
    if len(vault_hash) != 64 or any(char not in "0123456789abcdef" for char in vault_hash):
        raise LicenseError("The license.key contains an invalid VAULT_HASH. Request a replacement license.")
    return fields


def copy_license(source: Path) -> Path:
    source = Path(source).expanduser().resolve()
    read_license(source)
    destination = HERE / "license.key"
    if source != destination.resolve():
        shutil.copyfile(source, destination)
    print("  Full license.key envelope validated and installed")
    return destination


def resolve_release() -> dict[str, str | None]:
    """Resolve the latest release and its published SHA-256 digest."""
    request = urllib.request.Request(
        API_LATEST,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "plugict-setup"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except Exception as exc:
        raise SetupError(
            "GitHub release metadata could not be verified. "
            "Retry setup when GitHub is reachable; refusing an unverified vault download."
        ) from exc

    for asset in data.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            digest = asset.get("digest") or ""
            digest = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
            if not digest:
                raise SetupError(
                    "The latest PlugICT release has no published SHA-256 digest. "
                    "Refusing to install an unverified vault. Contact support."
                )
            return {
                "tag": data.get("tag_name", "latest"),
                "url": asset.get("browser_download_url", FALLBACK_URL),
                "digest": digest,
            }

    raise SetupError(f"{ASSET_NAME} is missing from the latest PlugICT release.")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(zip_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != destination and destination not in target.parents:
                raise SetupError("The release archive contains an unsafe path; refusing extraction.")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output)


def download_vault() -> None:
    zip_path = HERE / "plugict_download.zip"
    if zip_path.exists():
        zip_path.unlink()
    release = resolve_release()
    print(f"  Downloading vault {release['tag']}...")
    urllib.request.urlretrieve(str(release["url"]), zip_path)
    print(f"  Downloaded: {zip_path.stat().st_size / 1024 / 1024:.0f} MB")
    print("  Verifying SHA-256...")
    actual = file_sha256(zip_path)
    if actual != release["digest"]:
        zip_path.unlink(missing_ok=True)
        raise SetupError("Checksum mismatch — the download is corrupt or was tampered with. Re-run setup.py.")
    print("  Checksum verified")
    print("  Extracting...")
    _safe_extract(zip_path, HERE)
    zip_path.unlink(missing_ok=True)

    nested = HERE / "plugict"
    if nested.is_dir():
        for item in nested.iterdir():
            destination = HERE / item.name
            if not destination.exists():
                shutil.move(str(item), str(destination))
        shutil.rmtree(nested)
    print("  Vault extracted")


def ensure_runtime_files() -> None:
    missing = [name for name in RUNTIME_FILES if not (HERE / name).exists()]
    if missing:
        raise SetupError("Package is incomplete; missing: " + ", ".join(missing))


def verify_installation() -> None:
    """Run doctor plus direct and MCP smoke tests; fail closed on any failure."""
    ensure_runtime_files()
    python = runtime_python()
    if not python.exists():
        raise SetupError("Buyer .venv interpreter is missing.")
    command = [str(python), "-E", "-X", "utf8", str(HERE / "mcp_server.py"), "--doctor"]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
        env=child_env(),
    )
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise SetupError("Doctor failed; setup is not complete.\n" + detail[-3000:])
    print("  Doctor passed: license, vault integrity, dependencies, and retrieval are healthy")
    run_direct_search_test()
    run_smoke_test()


def verify() -> None:
    """Backward-compatible doctor-only hook for existing local tooling.

    The installer calls :func:`verify_installation`, which additionally runs
    the live MCP smoke test. This small hook preserves the old public helper
    for scripts that only want a doctor check.
    """
    command = [str(runtime_python()), "-E", "-X", "utf8", str(HERE / "mcp_server.py"), "--doctor"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, env=child_env())
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise SetupError("Doctor failed; setup is not complete.\n" + detail[-3000:])


def run_smoke_test() -> None:
    smoke = HERE / "smoke_test.py"
    if not smoke.exists():
        raise SetupError("smoke_test.py is missing; refusing to claim MCP setup success.")
    result = subprocess.run(
        [str(runtime_python()), "-E", "-X", "utf8", str(smoke)],
        capture_output=True,
        text=True,
        timeout=180,
        env=child_env(),
    )
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise SetupError("MCP smoke test failed; setup is not complete.\n" + detail[-3000:])
    print("  MCP smoke test passed: search_ict returned cited evidence")


def run_direct_search_test() -> None:
    """Exercise the non-MCP buyer path and require a cited result."""
    runner = HERE / "plugict_search.py"
    if not runner.exists():
        raise SetupError("plugict_search.py is missing; refusing to claim direct search readiness.")
    result = subprocess.run(
        [
            str(runtime_python()),
            "-E",
            "-X",
            "utf8",
            str(runner),
            "--query",
            "What is FVG in ICT?",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=child_env(),
    )
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise SetupError("Direct local search smoke test failed; setup is not complete.\n" + detail[-3000:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SetupError("Direct local search returned invalid JSON; setup is not complete.") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results or not any(item.get("url") for item in results if isinstance(item, dict)):
        raise SetupError("Direct local search returned no cited evidence; setup is not complete.")
    print("  Direct local search passed: local runner returned cited evidence")


def _config_env(temp_dir: Path, hf_home: Path) -> dict[str, str]:
    return {
        "ICT_TEMP_DIR": temp_dir.resolve().as_posix(),
        "HF_HOME": hf_home.resolve().as_posix(),
        "PYTHONNOUSERSITE": "1",
    }


def render_json_config(python: Path, server: Path, temp_dir: Path, hf_home: Path) -> str:
    config = {
        "mcpServers": {
            "plugict": {
                "command": python.resolve().as_posix(),
                "args": ["-E", "-X", "utf8", server.resolve().as_posix()],
                "env": _config_env(temp_dir, hf_home),
            }
        }
    }
    return json.dumps(config, indent=2) + "\n"


def render_hermes_config(python: Path, server: Path, temp_dir: Path, hf_home: Path) -> str:
    py = python.resolve().as_posix()
    srv = server.resolve().as_posix()
    env = _config_env(temp_dir, hf_home)
    lines = [
        "# Add this block under mcp_servers in your Hermes profile config.yaml",
        "mcp_servers:",
        "  plugict:",
        f'    command: "{py}"',
        f'    args: ["-E", "-X", "utf8", "{srv}"]',
        "    enabled: true",
        f"    connect_timeout: {CONFIG_CONNECT_TIMEOUT}",
        "    env:",
    ]
    lines.extend(f'      {key}: "{value}"' for key, value in env.items())
    return "\n".join(lines) + "\n"


def write_mcp_configs() -> None:
    """Write configs with the exact buyer interpreter, server, env, and timeout."""
    examples = HERE / "examples"
    examples.mkdir(parents=True, exist_ok=True)
    python = runtime_python()
    server = HERE / "mcp_server.py"
    dirs = runtime_dirs()
    generator = examples / "make_configs.py"
    if not generator.exists():
        raise SetupError("examples/make_configs.py is missing; refusing to generate unknown MCP paths.")
    # The checked-in generator is the canonical implementation. Execute it
    # with the buyer interpreter so generated files are real, not placeholders.
    subprocess.check_call([str(python), "-E", "-X", "utf8", str(generator)])
    print("  AI-agent config files generated with cold-start timeout and isolated runtime paths")


def print_mcp_config() -> None:
    print("\n=== MCP Configuration ===\n")
    print(render_hermes_config(runtime_python(), HERE / "mcp_server.py", runtime_dirs()["temp"], runtime_dirs()["hf_home"]))
    print(f"Runtime (native path): {runtime_python()}")
    print("Merge this top-level block into your Hermes profile config.yaml, restart Hermes, then ask:")
    print('  "Search PlugICT: what is FVG in ICT?"')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install and verify PlugICT for an AI agent")
    parser.add_argument("--license", dest="license_path", help="Path to the full license.key envelope")
    parser.add_argument("--reinstall", action="store_true", help="Re-download the release vault")
    parser.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting for a license path")
    args = parser.parse_args([] if argv is None else argv)

    print("=" * 60)
    print("  PlugICT — ICT Evidence Vault Setup")
    print("=" * 60)
    try:
        step("Checking Python")
        check_python()

        vault = HERE / "ict-vault.kevin"
        license_file = HERE / "license.key"
        if args.license_path:
            copy_license(Path(args.license_path))
        elif license_file.exists():
            read_license(license_file)
            print("  Existing full license.key envelope validated")
        elif args.non_interactive:
            raise LicenseError(
                "No license.key found. Pass --license /path/to/license.key; do not paste LICENSE_ID or PURCHASE_ID."
            )
        else:
            source = prompt("Path to your full license.key file (do not paste an ID or the license contents)")
            copy_license(Path(source))

        if args.reinstall or not vault.exists():
            step("Downloading verified vault")
            download_vault()
        else:
            print("  Encrypted vault already present — no download needed")

        step("Checking package")
        ensure_runtime_files()
        step("Creating isolated environment")
        create_runtime_environment()
        step("Installing dependencies")
        install_deps()
        step("Verifying installation")
        verify_installation()
        step("Generating MCP configs")
        write_mcp_configs()
        print_mcp_config()
        print("\n" + "=" * 60)
        print("  PlugICT is ready — direct local search and MCP smoke both passed.")
        print("  MCP is optional; buyer agents can use plugict_search.py directly.")
        print("=" * 60)
        return 0
    except (SetupError, OSError, subprocess.CalledProcessError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
