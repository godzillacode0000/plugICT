-- PlugICT Chatbar — D1 schema (chat limits, plans, chunk manifest, FTS5 fallback)
-- Applied to: plugict-chat-db (database_id 2687a536-4a12-4075-91d9-0a85851e0192)

-- Usage limits: authenticated Supabase user IDs only. ip_hash remains in the
-- historical composite key as an empty compatibility column.
CREATE TABLE IF NOT EXISTS chat_limits (
  user_id TEXT NOT NULL DEFAULT '',
  ip_hash TEXT NOT NULL DEFAULT '',
  questions_used INTEGER DEFAULT 0,
  first_question_at INTEGER,
  last_question_at INTEGER,
  PRIMARY KEY (user_id, ip_hash)
);

-- Active usage contract. Free is one lifetime row; each paid plan/day gets a
-- separate row, so upgrades and plan changes never inherit another allowance.
CREATE TABLE IF NOT EXISTS chat_usage_scoped (
  user_id TEXT NOT NULL,
  entitlement_scope TEXT NOT NULL,  -- free | premium | pro
  period_key TEXT NOT NULL,         -- lifetime | YYYY-MM-DD (UTC)
  questions_used INTEGER NOT NULL DEFAULT 0 CHECK (questions_used >= 0),
  first_question_at INTEGER,
  last_question_at INTEGER,
  PRIMARY KEY (user_id, entitlement_scope, period_key)
);

-- Provisioned subscription plan state. Automated Stripe synchronization is a
-- separate billing-system concern and is not claimed by this chat release.
CREATE TABLE IF NOT EXISTS user_plans (
  user_id TEXT PRIMARY KEY,
  plan TEXT DEFAULT 'free',          -- free | premium | pro
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  renews_at INTEGER,
  updated_at INTEGER
);

-- Chunk manifest (lossless provenance audit/debug)
CREATE TABLE IF NOT EXISTS vault_chunks (
  id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  chunk_idx INTEGER NOT NULL,
  r2_key TEXT NOT NULL,
  title TEXT,
  playlist TEXT,
  char_count INTEGER,
  start_ts TEXT,
  end_ts TEXT,
  start_seconds INTEGER,
  end_seconds INTEGER,
  source_file TEXT,
  timing_precision TEXT,
  chunker_version TEXT,
  content_hash TEXT,
  has_vector INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER
);

-- FTS5 fallback index (keyword BM25 when Vectorize unavailable).
-- Provenance fields are UNINDEXED but retained for exact source links.
CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
  chunk_id UNINDEXED,
  title UNINDEXED,
  video_id UNINDEXED,
  playlist UNINDEXED,
  start_ts UNINDEXED,
  end_ts UNINDEXED,
  start_seconds UNINDEXED,
  end_seconds UNINDEXED,
  source_file UNINDEXED,
  timing_precision UNINDEXED,
  chunker_version UNINDEXED,
  content_hash UNINDEXED,
  content,
  tokenize = 'porter'
);

-- Privacy-safe analytics only, not conversation history. Never store raw
-- prompts, answers, access tokens, email addresses, or OAuth payloads.
CREATE TABLE IF NOT EXISTS chat_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question_hash TEXT NOT NULL,
  plan TEXT DEFAULT 'free',
  latency_ms INTEGER,
  cache_hit INTEGER DEFAULT 0,
  created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chat_log_created ON chat_log(created_at);
