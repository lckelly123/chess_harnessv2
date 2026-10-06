-- Runs atomically with schema.sql under a schema-scoped advisory lock.
-- Existing position/run/pass identities and trace payloads survive unchanged.
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS queue_tag uuid;
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS failure_stage text;
ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS created_at timestamptz;
UPDATE model_runs SET created_at = coalesce(started_at, now()) WHERE created_at IS NULL;
ALTER TABLE model_runs ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE model_runs ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE model_runs ALTER COLUMN started_at DROP NOT NULL;
ALTER TABLE model_runs ALTER COLUMN started_at DROP DEFAULT;
ALTER TABLE model_runs DROP CONSTRAINT IF EXISTS model_runs_status_check;
ALTER TABLE model_runs ADD CONSTRAINT model_runs_status_check
    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped'));

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()
               AND table_name = 'model_runs' AND column_name = 'queue_id') THEN
        UPDATE model_runs SET queue_tag = queue_id WHERE queue_tag IS NULL;
    END IF;
    IF to_regclass('position_run_queue_items') IS NOT NULL THEN
        UPDATE model_runs r SET
            queue_tag = q.id,
            failure_stage = i.failure_stage,
            error = coalesce(i.error, r.error),
            status = CASE WHEN i.status = 'running' AND r.status = 'completed'
                              AND r.evaluation->>'status' = 'completed'
                          THEN 'completed' ELSE i.status END,
            config = r.config || jsonb_build_object(
                'queue_ordinal', i.ordinal,
                'queue', jsonb_build_object(
                    'dataset_version', q.dataset_version, 'split', q.split,
                    'model_selection', q.model_selection, 'created_at', q.created_at,
                    'stop_requested', q.status IN ('stopping', 'stopped')),
                'harness_name', q.harness_name, 'harness_version', q.harness_version,
                'queue_legacy', jsonb_build_object('queue', to_jsonb(q), 'item', to_jsonb(i),
                    'run_status', r.status, 'run_error', r.error))
        FROM position_run_queue_items i JOIN position_run_queues q ON q.id = i.queue_id
        WHERE i.run_id = r.id;

        -- Unstarted/skipped positions and failures before model creation become runs too.
        INSERT INTO model_runs (id, position_id, queue_tag, model, harness, config,
                                status, failure_stage, error, created_at, started_at, finished_at)
        SELECT gen_random_uuid(), i.position_id, q.id,
            coalesce(q.model_selection->>'model_id', 'qwen'), q.harness_id,
            jsonb_build_object('harness_name', q.harness_name, 'harness_version', q.harness_version,
                'queue_ordinal', i.ordinal,
                'queue', jsonb_build_object(
                    'dataset_version', q.dataset_version, 'split', q.split,
                    'model_selection', q.model_selection, 'created_at', q.created_at,
                    'stop_requested', q.status IN ('stopping', 'stopped')),
                'queue_legacy', jsonb_build_object('queue', to_jsonb(q), 'item', to_jsonb(i))),
            CASE WHEN q.status IN ('stopped', 'stopping') AND i.status = 'queued'
                 THEN 'skipped' ELSE i.status END,
            i.failure_stage, i.error, q.created_at, i.started_at,
            CASE WHEN q.status IN ('stopped', 'stopping') AND i.status = 'queued'
                 THEN coalesce(q.finished_at, now()) ELSE i.finished_at END
        FROM position_run_queue_items i JOIN position_run_queues q ON q.id = i.queue_id
        WHERE i.run_id IS NULL;

        UPDATE model_runs SET status = 'skipped', finished_at = coalesce(finished_at, now())
        WHERE status = 'queued' AND config->'queue'->>'stop_requested' = 'true';
        IF EXISTS (
            SELECT 1 FROM position_run_queue_items i
            LEFT JOIN model_runs r ON r.queue_tag = i.queue_id AND r.position_id = i.position_id
            WHERE r.id IS NULL OR (i.run_id IS NOT NULL AND r.id <> i.run_id)
        ) THEN
            RAISE EXCEPTION 'Queue migration did not preserve every scheduled position/run';
        END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()
               AND table_name = 'positions' AND column_name = 'source') THEN
        UPDATE positions p SET metadata = p.metadata || jsonb_build_object(
            'provenance', jsonb_build_object('source', p.source, 'source_game_id', p.source_game_id,
                'source_ply', p.source_ply, 'source_url', p.source_url, 'position_key', p.position_key));
    END IF;
    IF to_regclass('position_datasets') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM position_datasets d
                   WHERE NOT EXISTS (SELECT 1 FROM positions p WHERE p.dataset_version = d.version)) THEN
            RAISE EXCEPTION 'Cannot embed a dataset without any positions';
        END IF;
        UPDATE positions p SET metadata = p.metadata || jsonb_build_object('dataset', to_jsonb(d))
        FROM position_datasets d WHERE p.dataset_version = d.version;
    END IF;
    IF to_regclass('position_evaluations') IS NOT NULL THEN
        UPDATE positions p SET metadata = p.metadata || jsonb_build_object(
            'reference_evaluations', coalesce((SELECT jsonb_agg(to_jsonb(e) ORDER BY e.analysis_id)
                FROM position_evaluations e WHERE e.position_id = p.id), '[]'::jsonb));
        IF (SELECT count(*) FROM position_evaluations) <>
           (SELECT coalesce(sum(jsonb_array_length(metadata->'reference_evaluations')), 0) FROM positions) THEN
            RAISE EXCEPTION 'Reference evaluation migration count mismatch';
        END IF;
    END IF;
END $$;

UPDATE model_runs SET status = 'failed', failure_stage = 'evaluation',
    error = coalesce(error, evaluation->>'error', 'Evaluation failed.')
WHERE evaluation->>'status' = 'failed' AND failure_stage IS NULL;
UPDATE model_runs SET failure_stage = 'execution'
WHERE status = 'failed' AND failure_stage IS NULL;

-- No CASCADE: unexpected external dependencies abort the entire transaction.
DROP TABLE IF EXISTS position_run_queue_items;
ALTER TABLE model_runs DROP COLUMN IF EXISTS queue_id;
DROP TABLE IF EXISTS position_run_queues;
DROP TABLE IF EXISTS position_evaluations;
ALTER TABLE positions DROP CONSTRAINT IF EXISTS positions_dataset_version_fkey;
DROP TABLE IF EXISTS position_datasets;
ALTER TABLE positions DROP COLUMN IF EXISTS source, DROP COLUMN IF EXISTS source_game_id,
    DROP COLUMN IF EXISTS source_ply, DROP COLUMN IF EXISTS source_url,
    DROP COLUMN IF EXISTS position_key;
DROP INDEX IF EXISTS model_runs_position_started;
