-- Additive and repeatable: existing match history remains in its SQLite store.
CREATE TABLE IF NOT EXISTS position_datasets (
    version text PRIMARY KEY,
    description text NOT NULL,
    seed bigint NOT NULL,
    position_count integer NOT NULL CHECK (position_count > 0),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS positions (
    id uuid PRIMARY KEY,
    dataset_version text NOT NULL REFERENCES position_datasets(version),
    split text NOT NULL CHECK (split IN ('train', 'test')),
    phase text NOT NULL CHECK (phase IN ('opening', 'middlegame', 'endgame')),
    position_type text NOT NULL CHECK (position_type IN ('quiet', 'tactical')),
    fen text NOT NULL CHECK (length(fen) > 15),
    pgn_prefix text NOT NULL CHECK (length(pgn_prefix) > 0),
    last_move_uci text NOT NULL CHECK (last_move_uci ~ '^[a-h][1-8][a-h][1-8][qrbn]?$'),
    last_move_san text NOT NULL,
    source text NOT NULL CHECK (source IN ('lichess_game', 'lichess_puzzle')),
    source_game_id text NOT NULL CHECK (source_game_id ~ '^[A-Za-z0-9]{8}$'),
    source_ply integer NOT NULL CHECK (source_ply > 0),
    source_url text NOT NULL,
    position_key text NOT NULL CHECK (position_key ~ '^[0-9a-f]{64}$'),
    metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    -- One exercise per source game in a version prevents adjacent-position leakage.
    UNIQUE (dataset_version, source_game_id),
    -- Ignores move counters for duplicate detection, but retains full FEN/history above.
    UNIQUE (dataset_version, position_key)
);

CREATE INDEX IF NOT EXISTS positions_filters
    ON positions (dataset_version, split, phase, position_type);

CREATE TABLE IF NOT EXISTS position_evaluations (
    position_id uuid NOT NULL REFERENCES positions(id),
    analysis_id text NOT NULL,
    engine_name text NOT NULL,
    perspective text NOT NULL CHECK (perspective = 'side_to_move'),
    node_limit integer NOT NULL CHECK (node_limit > 0),
    best_move_uci text NOT NULL,
    best_score_cp integer,
    best_mate integer,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (position_id, analysis_id),
    CHECK ((best_score_cp IS NULL) <> (best_mate IS NULL))
);

CREATE TABLE IF NOT EXISTS model_runs (
    id uuid PRIMARY KEY,
    position_id uuid NOT NULL REFERENCES positions(id),
    model text NOT NULL,
    harness text NOT NULL,
    config jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(config) = 'object'),
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    final_move_uci text,
    cp_loss integer,
    classification text,
    evaluation jsonb CHECK (jsonb_typeof(evaluation) = 'object'),
    error text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE INDEX IF NOT EXISTS model_runs_position_started
    ON model_runs (position_id, started_at DESC, id);

-- No backfill: older attempts keep NULL rather than appearing evaluated.
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS expected_points_loss double precision
    CHECK (expected_points_loss >= 0 AND expected_points_loss <= 1);
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS better_moves jsonb
    CHECK (jsonb_typeof(better_moves) = 'array');

CREATE TABLE IF NOT EXISTS model_run_passes (
    run_id uuid NOT NULL REFERENCES model_runs(id) ON DELETE CASCADE,
    pass_number integer NOT NULL CHECK (pass_number > 0),
    phase text NOT NULL,
    tool_calls jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(tool_calls) = 'array'),
    working_notes text,
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    error text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    PRIMARY KEY (run_id, pass_number)
);

-- A frozen set membership and configuration for each sequential batch.
CREATE TABLE IF NOT EXISTS position_run_queues (
    id uuid PRIMARY KEY,
    dataset_version text NOT NULL REFERENCES position_datasets(version),
    split text NOT NULL CHECK (split IN ('train', 'test')),
    harness_id text NOT NULL,
    harness_name text NOT NULL,
    harness_version text NOT NULL,
    model_selection jsonb NOT NULL CHECK (jsonb_typeof(model_selection) = 'object'),
    status text NOT NULL CHECK (status IN ('queued', 'running', 'stopping', 'completed', 'stopped')),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS position_run_queues_one_active
    ON position_run_queues ((true)) WHERE status IN ('queued', 'running', 'stopping');

CREATE TABLE IF NOT EXISTS position_run_queue_items (
    queue_id uuid NOT NULL REFERENCES position_run_queues(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    position_id uuid NOT NULL REFERENCES positions(id),
    run_id uuid UNIQUE REFERENCES model_runs(id),
    status text NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped')),
    failure_stage text,
    error text,
    started_at timestamptz,
    finished_at timestamptz,
    PRIMARY KEY (queue_id, ordinal),
    UNIQUE (queue_id, position_id)
);

CREATE INDEX IF NOT EXISTS position_run_queue_items_status
    ON position_run_queue_items (queue_id, status, ordinal);
