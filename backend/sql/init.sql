-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Tenants table
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    domain VARCHAR(100) UNIQUE NOT NULL,
    language VARCHAR(10) DEFAULT 'zh-CN',
    accent_region VARCHAR(50) DEFAULT 'default',
    status VARCHAR(20) DEFAULT 'active',
    model_path VARCHAR(500),
    voiceprint_threshold FLOAT DEFAULT 0.70,
    settings JSON DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenants_domain ON tenants(domain);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status);

-- Users table (multi-tenant)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    username VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),
    role VARCHAR(20) DEFAULT 'user',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    last_login_ip VARCHAR(50),
    last_login_location VARCHAR(100)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tenant_username ON users(tenant_id, username);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tenant_email ON users(tenant_id, email);
CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);

-- WebAuthn credentials table
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id VARCHAR(500) UNIQUE NOT NULL,
    public_key VARCHAR(1000) NOT NULL,
    sign_count INTEGER DEFAULT 0,
    device_name VARCHAR(100),
    device_fingerprint VARCHAR(200),
    transports VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_webauthn_credentials_credential_id ON webauthn_credentials(credential_id);
CREATE INDEX IF NOT EXISTS idx_webauthn_credentials_user_id ON webauthn_credentials(user_id);

-- Voiceprints table with pgvector (multi-tenant)
CREATE TABLE IF NOT EXISTS voiceprints (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    feature_vector vector(200) NOT NULL,
    sample_name VARCHAR(100),
    source_mic_fingerprint VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_voiceprints_tenant_user ON voiceprints(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_voiceprints_vector ON voiceprints
    USING ivfflat (feature_vector vector_cosine_ops) WITH (lists = 100);

-- Login logs table
CREATE TABLE IF NOT EXISTS login_logs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username VARCHAR(50),
    auth_method VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL,
    ip_address VARCHAR(50),
    user_agent VARCHAR(500),
    location VARCHAR(100),
    device_fingerprint VARCHAR(200),
    similarity_score FLOAT,
    anomaly_detected BOOLEAN DEFAULT FALSE,
    fallback_triggered BOOLEAN DEFAULT FALSE,
    fallback_reason VARCHAR(200),
    verification_details JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_login_logs_tenant_created ON login_logs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_logs_status_created ON login_logs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_logs_created_at ON login_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_logs_user_id ON login_logs(user_id);

-- Anomaly events table
CREATE TABLE IF NOT EXISTS anomaly_events (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) DEFAULT 'medium',
    description TEXT,
    details JSON,
    related_login_ids JSON,
    status VARCHAR(20) DEFAULT 'new',
    reviewed_by INTEGER,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_anomalies_tenant_type_created ON anomaly_events(tenant_id, type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_created_at ON anomaly_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_type ON anomaly_events(type);
CREATE INDEX IF NOT EXISTS idx_anomalies_user_id ON anomaly_events(user_id);

-- Fallback cache table
CREATE TABLE IF NOT EXISTS fallback_caches (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cache_token VARCHAR(200) UNIQUE NOT NULL,
    original_auth_method VARCHAR(30),
    fallback_method VARCHAR(30) DEFAULT 'webauthn',
    ip_address VARCHAR(50),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_used BOOLEAN DEFAULT FALSE,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_fallback_cache_token ON fallback_caches(cache_token);
CREATE INDEX IF NOT EXISTS idx_fallback_expires ON fallback_caches(expires_at);
CREATE INDEX IF NOT EXISTS idx_fallback_tenant_user ON fallback_caches(tenant_id, user_id);

-- Reconciliation logs table
CREATE TABLE IF NOT EXISTS reconciliation_logs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cache_token VARCHAR(200),
    original_login_id INTEGER,
    voice_verification_status VARCHAR(20),
    voice_similarity FLOAT,
    status VARCHAR(20) DEFAULT 'pending',
    conflict_details JSON,
    reconciled_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_created ON reconciliation_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reconciliation_cache_token ON reconciliation_logs(cache_token);
CREATE INDEX IF NOT EXISTS idx_reconciliation_status ON reconciliation_logs(status);
CREATE INDEX IF NOT EXISTS idx_reconciliation_tenant ON reconciliation_logs(tenant_id);

-- Service health table
CREATE TABLE IF NOT EXISTS service_health (
    id SERIAL PRIMARY KEY,
    service_name VARCHAR(50) UNIQUE NOT NULL,
    is_healthy BOOLEAN DEFAULT TRUE,
    last_check TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_failure TIMESTAMP WITH TIME ZONE,
    failure_count INTEGER DEFAULT 0,
    status_message VARCHAR(500),
    metrics JSON
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_service_health_name ON service_health(service_name);

-- Insert default tenant
INSERT INTO tenants (name, domain, language, status, voiceprint_threshold, settings)
VALUES ('Default', 'default.local', 'zh-CN', 'active', 0.70,
    '{"anomaly_detection": true, "fallback_mode": true, "max_devices_per_user": 10, "max_voiceprints_per_user": 5}'::json)
ON CONFLICT (name) DO NOTHING;
