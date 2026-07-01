"""
ICT Knowledge Vault — MCP Server
=================================
Exposes the vault as tools for any MCP-compatible AI agent.
Usage: python mcp_server.py

Connect Claude/Cursor/Hermes/Codex:
  Add to config → agent auto-discovers tools → queries ICT vault.
"""

import sys, os, io, json, tarfile, struct, sqlite3, tempfile, shutil
from pathlib import Path
from datetime import datetime

VAULT_DIR = Path(__file__).parent.resolve()
VAULT_FILE = VAULT_DIR / "ict-vault.kevin"
LICENSE_FILE = VAULT_DIR / "license.key"

# ── Vault Loader ────────────────────────────────────────────────────────────
_db = None
_chroma_dir = None
_tmpdir = None
_licensed_to = "unknown"

def load_vault():
    """Decrypt and load vault. Called once on first tool use."""
    global _db, _chroma_dir, _tmpdir, _licensed_to
    
    if _db is not None:
        return  # Already loaded
    
    from cryptography.fernet import Fernet
    
    # Load license
    if not LICENSE_FILE.exists():
        raise RuntimeError("license.key not found")
    with open(LICENSE_FILE) as f:
        content = f.read()
    info = {}
    for line in content.strip().split('\n'):
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            info[k.strip()] = v.strip()
    
    buyer_key_raw = info.get('BUYER_KEY', '').encode()
    encrypted_vault_key_raw = info.get('ENCRYPTED_VAULT_KEY', '').encode()
    _licensed_to = info.get('LICENSED_TO', 'unknown')
    
    if not buyer_key_raw or not encrypted_vault_key_raw:
        raise RuntimeError("Invalid license.key — missing BUYER_KEY or ENCRYPTED_VAULT_KEY")
    
    # Decrypt vault key using buyer's unique key
    try:
        buyer_cipher = Fernet(buyer_key_raw)
        vault_key = buyer_cipher.decrypt(encrypted_vault_key_raw)
    except Exception:
        raise RuntimeError("Cannot unlock vault — license key invalid or corrupted")
    
    # Decrypt vault with vault key (AES-256 CTR)
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    
    vault_cipher = Cipher(algorithms.AES(vault_key), modes.CTR(encrypted[:16]), backend=default_backend())
    decryptor = vault_cipher.decryptor()
    decrypted = decryptor.update(encrypted[16:]) + decryptor.finalize()
    
    # Parse header
    version, db_size, chroma_size = struct.unpack('>IQQ', decrypted[:20])
    db_bytes = decrypted[20:20+db_size]
    chroma_bytes = decrypted[20+db_size:20+db_size+chroma_size]
    
    # Load DB to temp file
    _tmpdir = tempfile.mkdtemp(prefix='ict_vault_mcp_')
    db_path = os.path.join(_tmpdir, 'master.db')
    with open(db_path, 'wb') as f:
        f.write(db_bytes)
    _db = sqlite3.connect(db_path)
    
    # Extract ChromaDB
    _chroma_dir = os.path.join(_tmpdir, 'chroma')
    os.makedirs(_chroma_dir, exist_ok=True)
    chroma_tar = io.BytesIO(chroma_bytes)
    with tarfile.open(fileobj=chroma_tar) as tar:
        tar.extractall(path=_chroma_dir)


def cleanup():
    """Clean up temp files on shutdown."""
    global _db, _tmpdir
    if _db:
        _db.close()
    if _tmpdir:
        try:
            shutil.rmtree(_tmpdir)
        except Exception:
            pass


# ── Search Functions ────────────────────────────────────────────────────────

def search_vault(query, top_k=5, playlist=None):
    """Search vault using FTS5 + ChromaDB. Returns formatted results."""
    load_vault()
    
    results = []
    
    # --- FTS5 ---
    try:
        if playlist:
            fts = _db.execute(
                "SELECT title, video_id, start_ts, playlist, "
                "snippet(transcripts_fts, 2, '<b>', '</b>', '...', 80) as snippet "
                "FROM transcripts_fts WHERE content MATCH ? AND playlist = ? LIMIT ?",
                (query, playlist, top_k)
            ).fetchall()
        else:
            fts = _db.execute(
                "SELECT title, video_id, start_ts, playlist, "
                "snippet(transcripts_fts, 2, '<b>', '</b>', '...', 80) as snippet "
                "FROM transcripts_fts WHERE content MATCH ? LIMIT ?",
                (query, top_k)
            ).fetchall()
        
        for r in fts:
            results.append({
                'method': 'keyword',
                'title': r[0],
                'video_id': r[1],
                'timestamp': r[2],
                'playlist': r[3],
                'snippet': r[4],
            })
    except Exception:
        pass
    
    # --- ChromaDB ---
    try:
        import chromadb
        from chromadb.config import Settings
        
        client = chromadb.PersistentClient(
            path=_chroma_dir,
            settings=Settings(anonymized_telemetry=False)
        )
        collection = client.get_collection('ict_vault')
        
        where_filter = {'playlist': playlist} if playlist else None
        vec_out = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter
        )
        
        docs = vec_out.get('documents', [[]])[0]
        metas = vec_out.get('metadatas', [[]])[0]
        
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            # Avoid duplicates
            if not any(r.get('title') == meta.get('title') and r.get('timestamp') == meta.get('start_ts') for r in results):
                results.append({
                    'method': 'semantic',
                    'title': meta.get('title', 'Unknown'),
                    'video_id': meta.get('video_id', ''),
                    'timestamp': meta.get('start_ts', ''),
                    'playlist': meta.get('playlist', ''),
                    'snippet': doc[:500],
                })
    except Exception:
        pass
    
    return results[:top_k]


def get_all_playlists():
    """List all playlists with counts."""
    load_vault()
    rows = _db.execute(
        "SELECT playlist, COUNT(*) as cnt FROM transcripts_fts "
        "GROUP BY playlist ORDER BY cnt DESC"
    ).fetchall()
    return [{'playlist': r[0], 'video_count': r[1]} for r in rows]


def get_video_transcript(video_id=None, title_search=None):
    """Get full transcript for a specific video."""
    load_vault()
    
    if video_id:
        rows = _db.execute(
            "SELECT filename, title, video_id, duration, playlist, content "
            "FROM transcript_files WHERE video_id = ?", (video_id,)
        ).fetchall()
    elif title_search:
        rows = _db.execute(
            "SELECT filename, title, video_id, duration, playlist, content "
            "FROM transcript_files WHERE title LIKE ? LIMIT 3",
            (f'%{title_search}%',)
        ).fetchall()
    else:
        return {'error': 'Provide video_id or title_search'}
    
    results = []
    for r in rows:
        # Truncate content to avoid blowing up context
        content = r[5][:3000] if r[5] else ''
        results.append({
            'filename': r[0],
            'title': r[1],
            'video_id': r[2],
            'duration': r[3],
            'playlist': r[4],
            'content_preview': content,
        })
    
    return results


def explore_concept(concept):
    """Get KG connections and related content for an ICT concept."""
    load_vault()
    
    concept_upper = concept.upper() if len(concept) <= 5 else concept
    
    # KG relations
    relations = _db.execute(
        "SELECT from_entity, to_entity, relation_type, evidence FROM relations "
        "WHERE from_entity = ? OR to_entity = ?",
        (concept_upper, concept)
    ).fetchall()
    
    # Entity info
    entity = _db.execute(
        "SELECT name, type, description, source_count FROM entities WHERE name = ?",
        (concept_upper,)
    ).fetchone()
    
    # Search for relevant content
    content = search_vault(f"What is {concept}", top_k=3)
    
    return {
        'concept': concept,
        'entity_info': {
            'name': entity[0], 'type': entity[1],
            'description': entity[2], 'mention_count': entity[3]
        } if entity else None,
        'relations': [
            {'from': r[0], 'to': r[1], 'type': r[2], 'evidence': r[3]}
            for r in relations
        ],
        'top_content': content,
    }


def vault_stats():
    """Get vault statistics."""
    load_vault()
    
    meta = {}
    for row in _db.execute("SELECT key, value FROM vault_metadata").fetchall():
        meta[row[0]] = row[1]
    
    transcript_count = _db.execute("SELECT COUNT(*) FROM transcript_files").fetchone()[0]
    chunk_count = _db.execute("SELECT COUNT(*) FROM transcripts_fts").fetchone()[0]
    entity_count = _db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    playlist_count = _db.execute(
        "SELECT COUNT(DISTINCT playlist) FROM transcript_files"
    ).fetchone()[0]
    
    return {
        'version': meta.get('version', '1.0.0'),
        'build_date': meta.get('build_date', ''),
        'transcripts': transcript_count,
        'chunks': chunk_count,
        'entities': entity_count,
        'playlists': playlist_count,
        'licensed_to': _licensed_to,
    }


# ── MCP Server ──────────────────────────────────────────────────────────────
# Uses Anthropic's MCP Python SDK (pip install mcp)

import mcp.server.stdio
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationCapabilities
from mcp.types import Tool, TextContent

server = Server("ict-knowledge-vault")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="search_ict",
            description="Search the ICT (Inner Circle Trader) Knowledge Vault. 365 videos, 315+ hours of trading mentorship content transcribed and searchable. Use this to find what ICT says about any trading concept.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for. Examples: 'Fair Value Gap', 'Silver Bullet London', 'Order Block definition', 'how to trade FOMC'"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results (default 5, max 10)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    },
                    "playlist": {
                        "type": "string",
                        "description": "Filter by playlist. Options: '2022 ICT Mentorship', '2023 ICT Mentorship', 'ICT 2024 Mentorship', '2025 Lecture Series', '2026 SMC Lecture', '2016/2017 Mentorship', 'Forex Series', '2025 Storytellers', 'ICT Charter Content'"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="list_playlists",
            description="List all playlists in the ICT vault with video counts. Use this to understand what content is available before searching.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        # NOTE: get_transcript intentionally NOT exposed as a tool.
        # The vault is a search engine, not a transcript downloader.
        # Use search_ict to get relevant snippets with sources.
        Tool(
            name="explore_concept",
            description="Explore an ICT trading concept — get its definition, related concepts, and relevant content from the vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "concept": {
                        "type": "string",
                        "description": "ICT concept to explore: FVG, Order Block, Breaker, Silver Bullet, CISD, MSS, NDOG, NWOG, Killzone, Liquidity, Imbalance, Turtle Soup, etc."
                    }
                },
                "required": ["concept"]
            }
        ),
        Tool(
            name="vault_stats",
            description="Get statistics about the ICT Knowledge Vault — total videos, chunks, entities, and license info.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]


@server.call_tool()
async def call_tool(name, arguments):
    try:
        if name == "search_ict":
            results = search_vault(
                arguments.get('query', ''),
                top_k=arguments.get('top_k', 5),
                playlist=arguments.get('playlist')
            )
            if not results:
                return [TextContent(type="text", text="No results found. Try different keywords or check available playlists with list_playlists.")]
            
            output = f"Search results for: \"{arguments['query']}\"\n"
            output += f"Licensed to: {_licensed_to}\n\n"
            for i, r in enumerate(results):
                output += f"{i+1}. {r['title']}\n"
                output += f"   Method: {r['method']} | Timestamp: {r['timestamp']} | Playlist: {r['playlist']}\n"
                output += f"   \"{r['snippet'][:300]}...\"\n"
                if r.get('video_id'):
                    output += f"   Video: https://youtu.be/{r['video_id']}\n"
                output += "\n"
            return [TextContent(type="text", text=output)]
        
        elif name == "list_playlists":
            playlists = get_all_playlists()
            output = "ICT Knowledge Vault — Playlists\n\n"
            for p in playlists:
                output += f"- {p['playlist']}: {p['video_count']} videos\n"
            return [TextContent(type="text", text=output)]
        
        elif name == "get_transcript":
            results = get_video_transcript(
                video_id=arguments.get('video_id'),
                title_search=arguments.get('title_search')
            )
            if isinstance(results, dict) and 'error' in results:
                return [TextContent(type="text", text=results['error'])]
            
            output = ""
            for r in results:
                output += f"Title: {r['title']}\n"
                output += f"Video ID: {r['video_id']} | Duration: {r['duration']} | Playlist: {r['playlist']}\n"
                output += f"\n{r['content_preview']}\n"
                if len(r['content_preview']) >= 3000:
                    output += "\n[Content truncated — use search_ict for specific sections]\n"
            return [TextContent(type="text", text=output or "No transcript found.")]
        
        elif name == "explore_concept":
            result = explore_concept(arguments['concept'])
            output = f"ICT Concept: {result['concept']}\n\n"
            
            if result['entity_info']:
                ei = result['entity_info']
                output += f"Definition: {ei['description']}\n"
                output += f"Mentioned in {ei['mention_count']} transcript chunks\n\n"
            
            if result['relations']:
                output += "Related Concepts:\n"
                for rel in result['relations']:
                    output += f"  {rel['from']} → {rel['type']} → {rel['to']}\n"
                    if rel.get('evidence'):
                        output += f"    ({rel['evidence']})\n"
                output += "\n"
            
            if result['top_content']:
                output += "Top Content:\n"
                for c in result['top_content']:
                    output += f"  - {c['title']} ({c['timestamp']})\n"
                output += "\n"
            
            return [TextContent(type="text", text=output)]
        
        elif name == "vault_stats":
            stats = vault_stats()
            output = "ICT Knowledge Vault — Statistics\n\n"
            output += f"Version: {stats['version']}\n"
            output += f"Built: {stats['build_date']}\n"
            output += f"Transcripts: {stats['transcripts']}\n"
            output += f"Searchable chunks: {stats['chunks']:,}\n"
            output += f"Entities: {stats['entities']}\n"
            output += f"Playlists: {stats['playlists']}\n"
            output += f"Licensed to: {stats['licensed_to']}\n"
            return [TextContent(type="text", text=output)]
        
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# ── Main ────────────────────────────────────────────────────────────────────
async def main():
    import asyncio
    
    print("=" * 50)
    print("ICT Knowledge Vault — MCP Server")
    print("=" * 50)
    print(f"Licensed to: {_licensed_to}")
    print("Waiting for AI agent connection...")
    print()
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationCapabilities(
                sampling=None,
                experimental=None,
                roots=None
            )
        )

if __name__ == "__main__":
    import asyncio
    
    # Preload vault on startup
    try:
        load_vault()
    except Exception as e:
        print(f"WARNING: Vault not loaded: {e}")
        print("Server will start but tools may fail until vault is accessible.")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()
