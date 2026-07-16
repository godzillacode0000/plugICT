"""
generate_key.py — Generate UNIQUE license key per buyer
========================================================
Envelope encryption: each buyer gets their own key wrapping the vault key.
If one license leaks, only that buyer is affected — vault stays safe.

Usage:
    python generate_key.py "ali@gmail.com" "ICT-2026001"
    
Output: license_{email}.key
"""

import sys, hashlib, base64
from pathlib import Path
from datetime import datetime
from cryptography.fernet import Fernet

from artifact_paths import resolve_artifact_dir

VAULT_DIR = resolve_artifact_dir(Path(__file__).parent.parent.resolve())
VAULT_KEY_FILE = VAULT_DIR / ".vault_key"

def generate_license(buyer_email, purchase_id, vault_dir=None, output_dir=None):
    """Generate a unique license key for a buyer using envelope encryption.

    vault_dir overrides where .vault_key / .vault_sha256 are read. output_dir
    overrides where the license file is written; if omitted, it defaults to
    vault_dir for backwards-compatible local CLI behaviour. Returns
    (output_file, license_id).
    """
    vault_dir = Path(vault_dir) if vault_dir else VAULT_DIR
    output_dir = Path(output_dir) if output_dir else vault_dir
    vault_key_file = vault_dir / ".vault_key"

    # Load vault key (the actual decryption key for ict-vault.kevin)
    if not vault_key_file.exists():
        raise FileNotFoundError(f".vault_key not found in {vault_dir}. Run build.py first.")

    with open(vault_key_file, 'rb') as f:
        vault_key = f.read()

    encrypted_vault = vault_dir / "ict-vault.kevin"
    hash_file = vault_dir / ".vault_sha256"
    if not encrypted_vault.is_file():
        raise FileNotFoundError(f"ict-vault.kevin not found in {vault_dir}. Run build.py first.")
    if not hash_file.is_file():
        raise FileNotFoundError(f".vault_sha256 not found in {vault_dir}. Run build.py first.")
    vault_hash = hash_file.read_text(encoding="utf-8").strip().lower()
    if len(vault_hash) != 64 or any(c not in "0123456789abcdef" for c in vault_hash):
        raise ValueError(".vault_sha256 must contain one valid SHA-256 hex digest")
    actual_hash = hashlib.sha256(encrypted_vault.read_bytes()).hexdigest()
    if actual_hash != vault_hash:
        raise ValueError(".vault_sha256 does not match the actual encrypted vault")
    if len(vault_key) != 32:
        raise ValueError(f".vault_key must be exactly 32 bytes, got {len(vault_key)}")

    # Generate a UNIQUE key for this buyer
    buyer_key = Fernet.generate_key()
    
    # Wrap (encrypt) the vault key with the buyer's unique key
    buyer_cipher = Fernet(buyer_key)
    encrypted_vault_key = buyer_cipher.encrypt(vault_key)
    
    # Generate unique license ID for tracking
    hash_input = f"{buyer_email}:{purchase_id}:{datetime.now().isoformat()}"
    license_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16].upper()
    
    # License file: buyer's key + encrypted vault key + identity
    # Format: LICENSED_TO, PURCHASE_ID, LICENSE_ID, ISSUED, BUYER_KEY, ENCRYPTED_VAULT_KEY
    license_content = f"""# ICT Knowledge Vault — License Key
# =====================================
LICENSED_TO={buyer_email}
PURCHASE_ID={purchase_id}
LICENSE_ID={license_id}
ISSUED={datetime.now().strftime('%Y-%m-%d')}
BUYER_KEY={buyer_key.decode()}
ENCRYPTED_VAULT_KEY={encrypted_vault_key.decode()}
VAULT_HASH={vault_hash}
"""
    
    safe_email = buyer_email.replace('@', '_at_').replace('.', '_')
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"license_{safe_email}.key"

    with open(output_file, 'w') as f:
        f.write(license_content)
    
    print(f"License generated")
    print(f"   Buyer:    {buyer_email}")
    print(f"   Purchase: {purchase_id}")
    print(f"   License:  {license_id}")
    print(f"   File:     {output_file.name}")
    print()
    print("   Leaking one license allows traceability (you'll know who leaked it).")
    print("   Contact support for a replacement key if your license is compromised.")
    
    return output_file, license_id

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_key.py <buyer_email> [purchase_id]")
        print("Example: python generate_key.py ali@gmail.com ICT-2026001")
        sys.exit(1)
    
    buyer_email = sys.argv[1]
    purchase_id = sys.argv[2] if len(sys.argv) > 2 else f"ICT-{datetime.now().strftime('%Y%m%d%H%M')}"
    
    generate_license(buyer_email, purchase_id)
