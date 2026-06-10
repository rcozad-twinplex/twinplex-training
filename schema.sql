-- Twinplex Operator Training System — Supabase schema
-- Paste this into the Supabase SQL editor and click Run.

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    employee_id TEXT UNIQUE NOT NULL,
    pin_hash    TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'operator',
    lang_pref   TEXT NOT NULL DEFAULT 'en',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS completions (
    id               SERIAL PRIMARY KEY,
    operator_id      INTEGER NOT NULL REFERENCES users(id),
    module_code      TEXT NOT NULL,
    lang_used        TEXT DEFAULT 'en',
    started_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    lesson_viewed    INTEGER DEFAULT 0,

    pc1_submitted_at TIMESTAMP,
    pc1_score        INTEGER,
    pc1_max_auto     INTEGER,
    pc1_trainer_id   INTEGER REFERENCES users(id),
    pc1_passed       INTEGER,
    pc1_signed_at    TIMESTAMP,
    pc1_comments     TEXT,

    pc2_trainer_id   INTEGER REFERENCES users(id),
    pc2_passed       INTEGER,
    pc2_signed_at    TIMESTAMP,
    pc2_comments     TEXT,

    pc3_trainer_id   INTEGER REFERENCES users(id),
    pc3_passed       INTEGER,
    pc3_signed_at    TIMESTAMP,
    pc3_comments     TEXT,

    UNIQUE(operator_id, module_code)
);

CREATE TABLE IF NOT EXISTS pc1_answers (
    id             SERIAL PRIMARY KEY,
    completion_id  INTEGER NOT NULL REFERENCES completions(id),
    question_idx   INTEGER NOT NULL,
    answer_given   TEXT,
    auto_correct   INTEGER
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id             SERIAL PRIMARY KEY,
    completion_id  INTEGER NOT NULL REFERENCES completions(id),
    check_num      INTEGER NOT NULL,
    item_idx       INTEGER NOT NULL,
    passed         INTEGER DEFAULT 0,
    UNIQUE(completion_id, check_num, item_idx)
);

-- After running this schema, create your first admin account by running:
--   python seed_admin.py
-- from the project directory with DATABASE_URL set in your .env file.
