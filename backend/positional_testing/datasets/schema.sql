-- Three-table positional suite. Upgrade existing volumes through store.ensure_schema.
CREATE TABLE IF NOT EXISTS positions (
    id uuid PRIMARY KEY,
    dataset_version text NOT NULL,
    fen text NOT NULL CHECK (length(fen) > 15),
    pgn_prefix text NOT NULL CHECK (length(pgn_prefix) > 0),
    last_move_uci text NOT NULL CHECK (last_move_uci ~ '^[a-h][1-8][a-h][1-8][qrbn]?$'),
    last_move_san text NOT NULL,
    split text NOT NULL CHECK (split IN ('train', 'test')),
    phase text NOT NULL CHECK (phase IN ('opening', 'middlegame', 'endgame')),
    position_type text NOT NULL CHECK (position_type IN ('quiet', 'tactical')),
    metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS positions_filters
    ON positions (dataset_version, split, phase, position_type);
CREATE UNIQUE INDEX IF NOT EXISTS positions_source_game
    ON positions (dataset_version, (metadata->'provenance'->>'source_game_id'));
CREATE UNIQUE INDEX IF NOT EXISTS positions_board_key
    ON positions (dataset_version, (metadata->'provenance'->>'position_key'));

CREATE TABLE IF NOT EXISTS model_runs (
    id uuid PRIMARY KEY,
    position_id uuid NOT NULL REFERENCES positions(id),
    queue_tag uuid,
    model text NOT NULL,
    harness text NOT NULL,
    config jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(config) = 'object'),
    status text NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped')),
    final_move_uci text,
    classification text,
    cp_loss integer,
    expected_points_loss double precision CHECK (expected_points_loss BETWEEN 0 AND 1),
    better_moves jsonb CHECK (jsonb_typeof(better_moves) = 'array'),
    evaluation jsonb CHECK (jsonb_typeof(evaluation) = 'object'),
    failure_stage text,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);
-- Keep upgrades from older attempts with no evaluation columns additive.
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS expected_points_loss double precision
    CHECK (expected_points_loss BETWEEN 0 AND 1);
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS better_moves jsonb
    CHECK (jsonb_typeof(better_moves) = 'array');
CREATE INDEX IF NOT EXISTS model_runs_position_created
    ON model_runs (position_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS model_runs_queue_status
    ON model_runs (queue_tag, status) WHERE queue_tag IS NOT NULL;
CREATE INDEX IF NOT EXISTS model_runs_created
    ON model_runs (created_at DESC, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS model_runs_queue_position
    ON model_runs (queue_tag, position_id) WHERE queue_tag IS NOT NULL;

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
