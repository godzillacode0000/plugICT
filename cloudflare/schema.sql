PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS affiliate_codes (
  code TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'paused', 'closed')),
  token_hash TEXT UNIQUE,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS affiliate_clicks (
  click_id TEXT PRIMARY KEY,
  affiliate_code TEXT NOT NULL,
  visitor_hash TEXT NOT NULL,
  path TEXT NOT NULL,
  referrer_host TEXT,
  day TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (affiliate_code) REFERENCES affiliate_codes(code)
);

CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_code_day
  ON affiliate_clicks (affiliate_code, day);

CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_day
  ON affiliate_clicks (day);

CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_created_at
  ON affiliate_clicks (created_at, click_id);
