PRAGMA foreign_keys = ON;

CREATE TABLE customers (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name    TEXT NOT NULL,
  phone           TEXT,
  email           TEXT,
  notes           TEXT,
  opt_in          INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE customer_identities (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id      INTEGER NOT NULL,
  platform         TEXT NOT NULL CHECK(platform IN ('whatsapp','instagram','facebook')),
  platform_user_id TEXT NOT NULL,
  handle           TEXT,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ux_customer_identities_platform_user
ON customer_identities(platform, platform_user_id);

CREATE INDEX ix_customer_identities_customer
ON customer_identities(customer_id);

CREATE TABLE threads (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  platform           TEXT NOT NULL CHECK(platform IN ('whatsapp','instagram','facebook')),
  customer_id        INTEGER,
  external_thread_id TEXT,
  status             TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed','pending')),
  priority           TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low','normal','high','urgent')),
  tags               TEXT,
  last_activity_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL
);

CREATE INDEX ix_threads_platform_last_activity
ON threads(platform, last_activity_at DESC);

CREATE INDEX ix_threads_customer_platform
ON threads(customer_id, platform);

CREATE TABLE messages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id    INTEGER NOT NULL,
  platform     TEXT NOT NULL CHECK(platform IN ('whatsapp','instagram','facebook')),
  sender_type  TEXT NOT NULL CHECK(sender_type IN ('user','bot','agent','system')),
  sender_name  TEXT,
  content      TEXT NOT NULL,
  intent       TEXT,
  confidence   REAL,
  is_auto      INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX ix_messages_thread_time
ON messages(thread_id, created_at);

CREATE INDEX ix_messages_platform_time
ON messages(platform, created_at);

-- Full-text search (FTS5)
CREATE VIRTUAL TABLE messages_fts USING fts5(
  content,
  message_id UNINDEXED
);

CREATE TRIGGER trg_messages_ai_fts
AFTER INSERT ON messages
BEGIN
  INSERT INTO messages_fts(content, message_id) VALUES (new.content, new.id);
END;

CREATE TRIGGER trg_messages_ad_fts
AFTER DELETE ON messages
BEGIN
  DELETE FROM messages_fts WHERE message_id = old.id;
END;

CREATE TRIGGER trg_messages_au_fts
AFTER UPDATE OF content ON messages
BEGIN
  DELETE FROM messages_fts WHERE message_id = old.id;
  INSERT INTO messages_fts(content, message_id) VALUES (new.content, new.id);
END;

CREATE TRIGGER trg_messages_ai_thread_activity
AFTER INSERT ON messages
BEGIN
  UPDATE threads
  SET last_activity_at = new.created_at,
      updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
  WHERE id = new.thread_id;
END;

CREATE TABLE automation_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id    INTEGER NOT NULL,
  message_id   INTEGER,
  event_type   TEXT NOT NULL CHECK(event_type IN ('ingest','normalize','classify','respond','persist','error')),
  status       TEXT NOT NULL DEFAULT 'ok' CHECK(status IN ('ok','warn','error')),
  details_json TEXT,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE,
  FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE SET NULL
);

CREATE INDEX ix_automation_events_thread_time
ON automation_events(thread_id, created_at);

CREATE INDEX ix_automation_events_type_time
ON automation_events(event_type, created_at);

CREATE TABLE rules (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  intent        TEXT NOT NULL,
  keywords_json TEXT NOT NULL,
  priority      INTEGER NOT NULL DEFAULT 100,
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX ix_rules_enabled_priority
ON rules(enabled, priority);

CREATE TABLE response_templates (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  intent              TEXT NOT NULL,
  platform            TEXT CHECK(platform IN ('whatsapp','instagram','facebook')),
  language            TEXT NOT NULL DEFAULT 'es',
  template_text       TEXT NOT NULL,
  requires_slots_json TEXT,
  enabled             INTEGER NOT NULL DEFAULT 1,
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX ix_templates_intent_platform_enabled
ON response_templates(intent, platform, enabled);

CREATE TABLE metrics_daily (
  day                TEXT NOT NULL,
  platform           TEXT NOT NULL CHECK(platform IN ('whatsapp','instagram','facebook')),
  total_messages     INTEGER NOT NULL DEFAULT 0,
  user_messages      INTEGER NOT NULL DEFAULT 0,
  bot_messages       INTEGER NOT NULL DEFAULT 0,
  intent_counts_json TEXT,
  avg_response_ms    REAL,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY(day, platform)
);

CREATE INDEX ix_metrics_daily_platform_day
ON metrics_daily(platform, day);

CREATE VIEW v_thread_latest_message AS
SELECT
  t.id AS thread_id,
  t.platform,
  t.customer_id,
  t.status,
  t.priority,
  t.last_activity_at,
  m.id AS message_id,
  m.sender_type,
  m.content,
  m.created_at AS message_created_at
FROM threads t
LEFT JOIN messages m
  ON m.id = (
    SELECT id FROM messages
    WHERE thread_id = t.id
    ORDER BY created_at DESC
    LIMIT 1
  );
