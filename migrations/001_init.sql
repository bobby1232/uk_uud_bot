-- Idempotent schema for УК bot

CREATE TABLE IF NOT EXISTS user_consents (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    consented_at TIMESTAMPTZ NOT NULL,
    consent_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    full_name TEXT,
    phone TEXT,
    updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS admin_users (
    telegram_user_id BIGINT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'ADMIN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_categories (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    id BIGSERIAL PRIMARY KEY,
    category_id BIGINT NOT NULL REFERENCES service_categories(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    price_rub INT NOT NULL,
    duration_min INT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS requests (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    address_type TEXT NOT NULL, -- KNOWN / CUSTOM
    address_label TEXT NOT NULL,
    apartment TEXT,
    service_id BIGINT NOT NULL REFERENCES services(id) ON DELETE RESTRICT,
    service_name_snapshot TEXT NOT NULL,
    category_name_snapshot TEXT NOT NULL,
    price_snapshot_rub INT NOT NULL,
    booking_date DATE NOT NULL,
    status TEXT NOT NULL, -- CREATED/IN_PROGRESS/DONE/ARCHIVED
    awaiting_rating BOOLEAN NOT NULL DEFAULT FALSE,
    group_chat_id BIGINT,
    group_message_id BIGINT,
    pending_status TEXT,
    pending_price_rub INT,
    pending_status_requested_at TIMESTAMPTZ,
    pending_status_requested_by BIGINT,
    planned_at TIMESTAMPTZ,
    pending_planned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE requests ADD COLUMN IF NOT EXISTS pending_status TEXT;
ALTER TABLE requests ADD COLUMN IF NOT EXISTS pending_price_rub INT;
ALTER TABLE requests ADD COLUMN IF NOT EXISTS pending_status_requested_at TIMESTAMPTZ;
ALTER TABLE requests ADD COLUMN IF NOT EXISTS pending_status_requested_by BIGINT;
ALTER TABLE requests ADD COLUMN IF NOT EXISTS planned_at TIMESTAMPTZ;
ALTER TABLE requests ADD COLUMN IF NOT EXISTS pending_planned_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_requests_user ON requests(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_date ON requests(booking_date);

CREATE TABLE IF NOT EXISTS request_time_slots (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    time_from TIME NOT NULL,
    time_to TIME NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_slots_request ON request_time_slots(request_id);

CREATE TABLE IF NOT EXISTS request_ratings (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT UNIQUE NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    stars INT NOT NULL CHECK (stars BETWEEN 1 AND 5),
    comment TEXT,
    rated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS request_status_history (
    id BIGSERIAL PRIMARY KEY,
    request_id BIGINT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by BIGINT
);

CREATE INDEX IF NOT EXISTS idx_request_status_history_request ON request_status_history(request_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS draft_requests (
    telegram_user_id BIGINT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
