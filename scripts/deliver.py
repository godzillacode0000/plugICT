"""
deliver.py — Package vault for buyer delivery
==============================================
Bundles everything into a clean delivery folder ready for zip & send.

Usage:
    python deliver.py "ali@gmail.com" "ICT-2026001"

Output: delivery/{email_safe}/
"""

import sys, os, shutil
from pathlib import Path
from datetime import datetime

VAULT_DIR = Path(r"C:\Users\kevin\Hermes ICT Selling Idea")
DELIVERY_ROOT = VAULT_DIR / "delivery"

def deliver(buyer_email, purchase_id):
    """Package vault for a specific buyer."""
    
    print("=" * 60)
    print("ICT Knowledge Vault — Delivery Package")
    print("=" * 60)
    print(f"Buyer:    {buyer_email}")
    print(f"Purchase: {purchase_id}")
    print()
    
    safe_email = buyer_email.replace('@', '_at_').replace('.', '_')
    
    # ── Find license file ──
    license_files = list(VAULT_DIR.glob(f"license_{safe_email}*.key"))
    if not license_files:
        print("ERROR: License key not found. Run generate_key.py first:")
        print(f"   python generate_key.py \"{buyer_email}\" \"{purchase_id}\"")
        sys.exit(1)
    license_file = license_files[0]
    
    # ── Verify vault ──
    vault_file = VAULT_DIR / "ict-vault.kevin"
    if not vault_file.exists():
        print("ERROR: ict-vault.kevin not found. Run build.py first.")
        sys.exit(1)
    
    # ── Create delivery folder ──
    delivery_dir = DELIVERY_ROOT / safe_email
    if delivery_dir.exists():
        try:
            shutil.rmtree(str(delivery_dir))
        except PermissionError:
            # Folder locked, use timestamped name
            delivery_dir = DELIVERY_ROOT / f"{safe_email}_{datetime.now().strftime('%H%M%S')}"
    
    delivery_dir.mkdir(parents=True, exist_ok=True)
    
    # ── Copy vault ──
    print("[1/6] Copying encrypted vault...")
    shutil.copy2(vault_file, delivery_dir / "ict-vault.kevin")
    vault_size = (delivery_dir / "ict-vault.kevin").stat().st_size / 1024 / 1024
    print(f"  OK ict-vault.kevin ({vault_size:.0f} MB)")
    
    # ── Copy license ──
    print("[2/6] Copying license key...")
    shutil.copy2(license_file, delivery_dir / "license.key")
    print("  OK license.key")
    
    # ── Copy query.py ──
    print("[3/6] Copying query.py...")
    if (VAULT_DIR / "query.py").exists():
        shutil.copy2(VAULT_DIR / "query.py", delivery_dir / "query.py")
        print("  OK query.py")
    else:
        print("  WARNING: query.py not found in vault root")
    
    # ── Copy mcp_server.py ──
    print("[4/6] Copying mcp_server.py...")
    if (VAULT_DIR / "mcp_server.py").exists():
        shutil.copy2(VAULT_DIR / "mcp_server.py", delivery_dir / "mcp_server.py")
        print("  OK mcp_server.py")
    else:
        print("  WARNING: mcp_server.py not found in vault root")
    
    # ── Write requirements.txt ──
    req_file = delivery_dir / "requirements.txt"
    req_file.write_text("""cryptography>=41.0.0
chromadb>=0.4.0
sentence-transformers>=2.2.0
mcp>=1.0.0
""")
    print("  OK requirements.txt")
    
    # ── Write setup.bat ──
    setup_bat = delivery_dir / "setup.bat"
    setup_bat.write_text("""@echo off
echo ========================================
echo ICT Knowledge Vault - Setup
echo ========================================
echo.
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Testing vault...
python query.py "Fair Value Gap"
echo.
echo ========================================
echo Setup complete!
echo Run: python query.py "your question"
echo Or: python mcp_server.py (for AI agent)
echo ========================================
pause
""")
    print("  OK setup.bat")
    
    # ── Create examples folder ──
    print("[5/6] Creating example configs...")
    examples_dir = delivery_dir / "examples"
    examples_dir.mkdir(exist_ok=True)
    
    # Claude Desktop config
    claude_config = examples_dir / "claude_desktop_config.json"
    claude_config.write_text(f"""{{
  "mcpServers": {{
    "ict-knowledge-vault": {{
      "command": "python",
      "args": ["{delivery_dir.as_posix()}/mcp_server.py"],
      "env": {{
        "VAULT_PATH": "{delivery_dir.as_posix()}"
      }}
    }}
  }}
}}
""")
    
    # Cursor config
    cursor_config = examples_dir / "cursor_mcp.json"
    cursor_config.write_text(f"""{{
  "mcpServers": {{
    "ict-knowledge-vault": {{
      "command": "python",
      "args": ["{delivery_dir.as_posix()}/mcp_server.py"]
    }}
  }}
}}
""")
    
    # Hermes config
    hermes_config = examples_dir / "hermes_config.yaml"
    hermes_config.write_text(f"""# Add to ~/.hermes/profiles/<name>/config.yaml
mcp_servers:
  ict-knowledge-vault:
    command: python
    args: ["{delivery_dir.as_posix()}/mcp_server.py"]
    env:
      VAULT_PATH: "{delivery_dir.as_posix()}"
""")
    
    print("  OK examples/")
    
    # ── Copy docs ──
    print("[6/6] Copying documentation...")
    docs_dir = delivery_dir / "docs"
    docs_dir.mkdir(exist_ok=True)
    
    src_docs = VAULT_DIR / "docs"
    if src_docs.exists():
        for doc in src_docs.glob("*.md"):
            shutil.copy2(doc, docs_dir / doc.name)
    
    # Extract license_id from key file
    with open(license_file) as f:
        lic_content = f.read()
    lic_id = "unknown"
    for line in lic_content.strip().split('\n'):
        if line.startswith('LICENSE_ID='):
            lic_id = line.split('=', 1)[1].strip()
    
    # Write README
    readme = docs_dir / "README.md"
    readme.write_text(f"""# ICT Knowledge Vault

## Quick Start

```
setup.bat          # Install dependencies
python query.py "Fair Value Gap"   # Search the vault
```

## Connect to AI Agent

```
python mcp_server.py   # Start MCP server
```
Then add `examples/claude_desktop_config.json` to Claude Desktop config.

See `AI-AGENT-GUIDE.md` for full setup guide.

## License

Licensed to: **{buyer_email}**
Purchase ID: {purchase_id}
License ID: {purchase_id}

Do not share. Your license is traceable.
""")
    
    # ── Summary ──
    print()
    total_size = sum(f.stat().st_size for f in delivery_dir.rglob('*') if f.is_file()) / 1024 / 1024
    
    print("=" * 60)
    print("DELIVERY PACKAGE READY")
    print(f"   Folder: {delivery_dir}")
    print(f"   Size:   {total_size:.0f} MB")
    print()
    print("Contents:")
    for f in sorted(delivery_dir.rglob('*')):
        if f.is_file():
            rel = f.relative_to(delivery_dir)
            size = f.stat().st_size
            icon = '🔑' if f.name == 'license.key' else '📦' if f.name.endswith('.kevin') else '🐍' if f.suffix == '.py' else '📄' if f.suffix == '.md' else '⚙️' if f.suffix in ('.json','.yaml','.bat') else '📁'
            print(f"   {icon} {rel} ({size/1024:.0f} KB)")
    print()
    print("Next: Zip this folder and send to buyer.")
    print("  Right-click folder → Send to → Compressed (zipped) folder")
    print("=" * 60)
    
    return delivery_dir

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python deliver.py <buyer_email> [purchase_id]")
        print("Example: python deliver.py ali@gmail.com ICT-2026001")
        sys.exit(1)
    
    buyer_email = sys.argv[1]
    purchase_id = sys.argv[2] if len(sys.argv) > 2 else f"ICT-{datetime.now().strftime('%Y%m%d%H%M')}"
    
    deliver(buyer_email, purchase_id)
