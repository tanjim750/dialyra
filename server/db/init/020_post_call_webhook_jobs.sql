CREATE TABLE IF NOT EXISTS post_call_webhook_jobs (
  id SERIAL PRIMARY KEY,
  business_id INTEGER NOT NULL REFERENCES businesses(id),

  call_action_id VARCHAR(64) NOT NULL,
  call_session_id VARCHAR(128) NOT NULL,
  call_log_uuid VARCHAR(64),

  node_id INTEGER REFERENCES flow_nodes(id),
  node_key VARCHAR(128),
  sequence_no INTEGER NOT NULL DEFAULT 1,

  method VARCHAR(16) NOT NULL,
  url TEXT NOT NULL,
  auth_json TEXT,
  headers_json TEXT,
  payload_json TEXT,
  timeout_seconds INTEGER NOT NULL DEFAULT 5,

  idempotency_key VARCHAR(255) NOT NULL UNIQUE,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_retry_at TIMESTAMP WITHOUT TIME ZONE,

  last_error TEXT,
  last_response_code INTEGER,
  last_response_body TEXT,
  last_attempt_at TIMESTAMP WITHOUT TIME ZONE,
  completed_at TIMESTAMP WITHOUT TIME ZONE,

  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_post_call_webhook_jobs_business_id
  ON post_call_webhook_jobs (business_id);

CREATE INDEX IF NOT EXISTS idx_post_call_webhook_jobs_call_action_id
  ON post_call_webhook_jobs (call_action_id);

CREATE INDEX IF NOT EXISTS idx_post_call_webhook_jobs_call_session_id
  ON post_call_webhook_jobs (call_session_id);

CREATE INDEX IF NOT EXISTS idx_post_call_webhook_jobs_status
  ON post_call_webhook_jobs (status);

CREATE INDEX IF NOT EXISTS idx_post_call_webhook_jobs_next_retry_at
  ON post_call_webhook_jobs (next_retry_at);

CREATE INDEX IF NOT EXISTS idx_post_call_webhook_jobs_created_at
  ON post_call_webhook_jobs (created_at);

