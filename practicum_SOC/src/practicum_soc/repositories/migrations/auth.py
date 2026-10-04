"""Identidades de operadores; no están relacionadas con normalized_events.user_key."""

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_users (
    user_id TEXT PRIMARY KEY,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('administrator', 'analyst')),
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at_utc TEXT NOT NULL,
    UNIQUE(issuer, subject)
);
CREATE TABLE IF NOT EXISTS platform_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES platform_users(user_id),
    csrf_token TEXT NOT NULL,
    expires_at BIGINT NOT NULL,
    last_seen BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_platform_session_user ON platform_sessions(user_id);
CREATE TABLE IF NOT EXISTS oidc_login_attempts (
    state_hash TEXT PRIMARY KEY,
    browser_hash TEXT NOT NULL,
    nonce TEXT NOT NULL,
    verifier TEXT NOT NULL,
    expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_audit (
    audit_id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    action TEXT NOT NULL,
    target_id TEXT NOT NULL,
    details_json TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_auth_guard (
    singleton INTEGER PRIMARY KEY,
    revision BIGINT NOT NULL
);
INSERT INTO platform_auth_guard VALUES (1, 0) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS platform_rate_limits (
    scope TEXT NOT NULL,
    subject_hash TEXT NOT NULL,
    window_started BIGINT NOT NULL,
    hits BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    PRIMARY KEY(scope, subject_hash, window_started)
);
CREATE INDEX IF NOT EXISTS idx_rate_expiry ON platform_rate_limits(expires_at);
CREATE INDEX IF NOT EXISTS idx_audit_time ON platform_audit(occurred_at_utc);
CREATE TABLE IF NOT EXISTS platform_config_observations (
    filename TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL
);
"""
