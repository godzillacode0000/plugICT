"""
build.py — Build encrypted ICT Knowledge Vault
================================================
Envelope encryption:
  vault_key (random) → encrypts vault
  master_key → saved for generate_key.py to wrap per-buyer

Output: ict-vault.kevin + .vault_key (keep both secret)
"""

import os, sys, sqlite3, shutil, io, tarfile, struct
from pathlib import Path
from datetime import datetime

VAULT_DIR = Path(r"C:\Users\kevin\Hermes ICT Selling Idea")
OUTPUT_FILE = VAULT_DIR / "ict-vault.kevin"
VAULT_KEY_FILE = VAULT_DIR / ".vault_key"  # Keep secret! Used by generate_key.py
MASTER_KEY_FILE = VAULT_DIR / ".master_key"  # Keep secret! Fallback only

print("=" * 60)
print("ICT Knowledge Vault — Encrypted Build")
print("=" * 60)

# ── Step 1: Verify ──
print("\n[1/5] Verifying source files...")
vectors_dir = VAULT_DIR / "_vectors"
kg_db_path = VAULT_DIR / "kg.db"

for p in [vectors_dir, kg_db_path]:
    if not p.exists():
        print(f"  ERROR: {p.name} missing. Run ict_ingest.py first.")
        sys.exit(1)
    size = sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) if p.is_dir() else p.stat().st_size
    print(f"  OK {p.name} ({size/1024/1024:.0f} MB)")

md_count = len([f for f in VAULT_DIR.glob("*.md") if f.name not in ('index.md','README.md','CATALOG.md')])
print(f"  OK {md_count} transcripts")

# ── Step 2: Build master SQLite ──
print("\n[2/5] Building master database...")

master_db = VAULT_DIR / "_build_master.db"
if master_db.exists():
    master_db.unlink()

src = sqlite3.connect(str(kg_db_path))
dst = sqlite3.connect(str(master_db))
src.backup(dst)

dst.execute("""
    CREATE TABLE IF NOT EXISTS transcript_files (
        id INTEGER PRIMARY KEY, filename TEXT, title TEXT,
        video_id TEXT, duration TEXT, playlist TEXT, content TEXT, created TEXT
    )
""")

transcripts = [f for f in sorted(VAULT_DIR.glob("*.md")) 
               if f.name not in ('index.md','README.md','CATALOG.md')]

for fp in transcripts:
    with open(fp, encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    title = fp.stem; video_id = ''; duration = ''
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    k, v = k.strip(), v.strip().strip('"')
                    if k == 'title': title = v
                    elif k == 'video_id': video_id = v
                    elif k == 'duration': duration = v
    
    name = fp.name
    if '2023 ICT Mentorship' in name: playlist = '2023 ICT Mentorship'
    elif '2025 Lecture Series' in name: playlist = '2025 Lecture Series'
    elif 'ICT 2024 Mentorship' in name: playlist = 'ICT 2024 Mentorship'
    elif '2026' in name and 'SMC' in name: playlist = '2026 SMC Lecture'
    elif '2022 ICT Mentorship' in name: playlist = '2022 ICT Mentorship'
    elif '2016' in name or '2017' in name: playlist = '2016/2017 Mentorship'
    elif 'Forex' in name: playlist = 'Forex Series'
    elif 'Storytellers' in name: playlist = '2025 Storytellers'
    elif 'Charter' in name: playlist = 'ICT Charter Content'
    else: playlist = 'Other / Misc'
    
    dst.execute(
        "INSERT INTO transcript_files VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)",
        (fp.name, title, video_id, duration, playlist, content, datetime.now().isoformat())
    )

dst.execute("CREATE TABLE IF NOT EXISTS vault_metadata (key TEXT PRIMARY KEY, value TEXT)")
dst.execute("INSERT OR REPLACE INTO vault_metadata VALUES ('version', '1.0.0')")
dst.execute("INSERT OR REPLACE INTO vault_metadata VALUES ('build_date', ?)", (datetime.now().isoformat(),))
dst.execute("INSERT OR REPLACE INTO vault_metadata VALUES ('total_transcripts', ?)", (str(len(transcripts)),))

dst.commit()
src.close()
dst.close()

db_size = master_db.stat().st_size / 1024 / 1024
print(f"  OK Master DB: {db_size:.0f} MB")

with open(master_db, 'rb') as f:
    db_bytes = f.read()

# ── Step 3: Package ChromaDB ──
print("\n[3/5] Packaging ChromaDB vectors...")

chroma_tar_io = io.BytesIO()
with tarfile.open(fileobj=chroma_tar_io, mode='w') as tar:
    for root, dirs, files in os.walk(vectors_dir):
        for file in files:
            full_path = os.path.join(root, file)
            arcname = os.path.relpath(full_path, vectors_dir)
            tar.add(full_path, arcname=arcname)

chroma_bytes = chroma_tar_io.getvalue()
chroma_size = len(chroma_bytes) / 1024 / 1024
print(f"  OK ChromaDB tar: {chroma_size:.0f} MB")

# ── Step 4: Encrypt with vault key ──
print("\n[4/5] Encrypting vault...")

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import secrets

# Generate unique vault key (32 bytes for AES-256)
vault_key = secrets.token_bytes(32)

# Encrypt large package with AES-CTR (supports streaming)
iv = secrets.token_bytes(16)

# Package: [version:4][db_size:8][chroma_size:8][db_bytes][chroma_bytes]
package = struct.pack('>IQQ', 1, len(db_bytes), len(chroma_bytes)) + db_bytes + chroma_bytes

cipher = Cipher(algorithms.AES(vault_key), modes.CTR(iv), backend=default_backend())
encryptor = cipher.encryptor()
encrypted_package = encryptor.update(package) + encryptor.finalize()

# Prepend IV to encrypted data
final_encrypted = iv + encrypted_package

with open(OUTPUT_FILE, 'wb') as f:
    f.write(final_encrypted)

# Compute SHA-256 for integrity verification
import hashlib
vault_hash = hashlib.sha256(final_encrypted).hexdigest()
hash_file = VAULT_DIR / ".vault_sha256"
with open(hash_file, 'w') as f:
    f.write(vault_hash)

# Save vault key (raw 32 bytes, for generate_key.py to wrap per-buyer)
with open(VAULT_KEY_FILE, 'wb') as f:
    f.write(vault_key)
os.chmod(VAULT_KEY_FILE, 0o600)

# Also save master key as backup
master_key = Fernet.generate_key()
with open(MASTER_KEY_FILE, 'wb') as f:
    f.write(master_key)
os.chmod(MASTER_KEY_FILE, 0o600)

# Cleanup
master_db.unlink()

vault_size = OUTPUT_FILE.stat().st_size / 1024 / 1024
print(f"  OK Vault: {vault_size:.0f} MB")
print()
print("=" * 60)
print("BUILD COMPLETE")
print(f"   {OUTPUT_FILE.name}: {vault_size:.0f} MB")
print(f"   .vault_key: KEEP SECRET (used by generate_key.py)")
print(f"   .master_key: KEEP SECRET (backup)")
print("=" * 60)
