import { ChevronRight, ListOrdered, LoaderCircle, RefreshCw, RotateCcw, Square } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import { matchApi } from "../api/client";
import { CODEX_TRAINING_ID, type CodexWorkerStatus } from "../api/codex";
import type { HarnessVersion, ModelSelection, PositionalTestPosition, PositionQueueDetail, PositionQueueItem, PositionQueueSummary } from "../api/contracts";
import { tagLabel } from "./positionFilters";

const active = (queue: PositionQueueSummary) => ["queued", "running", "stopping"].includes(queue.status);
const modelName = (selection: PositionQueueSummary["modelSelection"]) => selection.modelId === "codex" ? `Codex · ${selection.modelName} · ${selection.reasoningEffort} reasoning` : selection.modelId === "gpt-terra" ? "GPT Terra" : `${selection.modelId === "unsloth" ? "Unsloth" : "LM Studio"} · ${selection.modelName ?? "loaded model"}`;
const message = (caught: unknown) => caught instanceof Error ? caught.message : "Queue unavailable. Retry to reconnect.";
const setName = (split: string) => split === "train" ? "Training" : "Test";

interface PositionQueueProps {
  positions: PositionalTestPosition[];
  harnesses: HarnessVersion[];
  modelSelection: ModelSelection;
  modelReady: boolean;
  codexWorker: CodexWorkerStatus | null;
  singleRunning: boolean;
  onActiveChange: (active: boolean) => void;
  onInspect: (positionId: string, runId: string | null) => void;
}

export function PositionQueue({ positions, harnesses, modelSelection, modelReady, codexWorker, singleRunning, onActiveChange, onInspect }: PositionQueueProps) {
  const id = useId();
  const [name, setQueueName] = useState("");
  const [split, setSplit] = useState<"train" | "test">("train");
  const [dataset, setDataset] = useState("");
  const [harnessId, setHarnessId] = useState("");
  const [queues, setQueues] = useState<PositionQueueSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [retrySourceId, setRetrySourceId] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [queue, setQueue] = useState<PositionQueueDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [failedOnly, setFailedOnly] = useState(false);
  const datasets = useMemo(() => [...new Set(positions.map((p) => p.datasetVersion))].sort().reverse(), [positions]);
  const datasetVersion = datasets.includes(dataset) ? dataset : datasets[0] ?? "";
  const count = positions.filter((p) => p.split === split && p.datasetVersion === datasetVersion).length;
  const positionsById = useMemo(() => new Map(positions.map((p) => [p.id, p])), [positions]);
  const hasActive = queues.some(active);
  const selected = queue?.id === selectedId || !selectedId ? queue : null;
  const current = selected?.items.find((item) => item.status === "running");
  const isCodex = harnessId === CODEX_TRAINING_ID;
  const ready = isCodex ? !!codexWorker?.online && !codexWorker.active_run_id : modelReady;
  const validHarness = isCodex || harnesses.some((harness) => harness.id === harnessId);
  const nextModel = isCodex ? codexWorker?.online ? `Codex · ${codexWorker.model} · ${codexWorker.reasoning_effort} reasoning` : "Codex · Windows worker offline" : modelName(modelSelection);
  const retrySources = queues.filter((item) => item.failed > 0 && ["completed", "stopped"].includes(item.status));
  const retrySource = retrySources.find((item) => item.id === retrySourceId);
  const retryBlock = singleRunning ? "The single-position run must finish before retrying." : hasActive ? "Finish or stop the active queue and wait for its current position to finish before starting a retry." : retrySource?.modelSelection.modelId === "codex" ? !codexWorker?.online ? "Start the Windows Codex worker to retry these positions." : codexWorker.active_run_id ? "The Windows worker must finish its current run before retrying." : null : null;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const result = await matchApi.listPositionQueues();
        const nextId = result.items.some((item) => item.id === selectedId) ? selectedId : result.items[0]?.id;
        const detail = nextId ? await matchApi.getPositionQueue(nextId) : null;
        if (cancelled) return;
        setQueues(result.items);
        setQueue(detail);
        if (selectedId && selectedId !== nextId) setSelectedId(nextId ?? "");
        onActiveChange(result.items.some(active));
        setError(null);
      } catch (caught) {
        if (!cancelled) setError(message(caught));
      } finally {
        if (!cancelled) {
          setLoading(false);
          timer = setTimeout(() => void load(), 2000);
        }
      }
    };
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [selectedId, revision, onActiveChange]);

  const start = async () => {
    if (!count || !validHarness || hasActive || singleRunning || pending || error || !ready) return;
    setPending(true);
    setCommandError(null);
    try {
      const result = await matchApi.createPositionQueue({ name: name.trim() || undefined, split, datasetVersion, harnessId, ...(isCodex ? {} : { modelSelection }) });
      setQueues((previous) => [result, ...previous.filter((q) => q.id !== result.id)]);
      setQueue(result);
      setSelectedId(result.id);
      setQueueName("");
      setFailedOnly(false);
      onActiveChange(true);
    } catch (caught) {
      setCommandError(message(caught));
    } finally {
      setRevision((value) => value + 1);
      setPending(false);
    }
  };

  const stop = async () => {
    if (!selected || pending) return;
    setPending(true);
    setCommandError(null);
    try {
      const result = await matchApi.stopPositionQueue(selected.id);
      setQueue(result);
      setQueues((previous) => previous.map((q) => q.id === result.id ? result : q));
    } catch (caught) {
      setCommandError(message(caught));
    } finally {
      setPending(false);
      setRevision((value) => value + 1);
    }
  };

  const retryFailed = async () => {
    if (!retrySource || retryBlock || loading || pending || error) return;
    setPending(true);
    setRetrying(true);
    setCommandError(null);
    try {
      const result = await matchApi.retryFailedPositionQueue(retrySource.id);
      setQueues((previous) => [result, ...previous.filter((q) => q.id !== result.id)]);
      setQueue(result);
      setSelectedId(result.id);
      setFailedOnly(false);
      setExpanded(true);
      onActiveChange(true);
    } catch (caught) {
      setCommandError(message(caught));
    } finally {
      setRetrying(false);
      setPending(false);
      setRevision((value) => value + 1);
    }
  };

  const inspect = (item: PositionQueueItem) => onInspect(item.positionId, item.runId);
  return (
    <section className="position-queue" aria-labelledby={`${id}-heading`}>
      <header className="position-queue__heading">
        <div><h2 id={`${id}-heading`}>Run a full set</h2><p>One position at a time, including evaluation. Failures are saved and the queue continues.</p></div>
        <span className="position-queue__model">New queue: <strong>{nextModel}</strong></span>
      </header>
      <form className="position-queue__form" onSubmit={(event) => { event.preventDefault(); void start(); }}>
        <label className="field-control position-queue__name" htmlFor={`${id}-name`}><span>Queue name (optional)</span><input id={`${id}-name`} value={name} maxLength={120} disabled={pending} placeholder="e.g. Qwen · revised prompt · training" autoComplete="off" onChange={(event) => setQueueName(event.target.value)} /></label>
        <label className="field-control" htmlFor={`${id}-set`}><span>Position set</span><select id={`${id}-set`} value={split} disabled={pending} onChange={(event) => setSplit(event.target.value as "train" | "test")}><option value="train">Training</option><option value="test">Test</option></select></label>
        <label className="field-control" htmlFor={`${id}-dataset`}><span>Dataset</span><select id={`${id}-dataset`} value={datasetVersion} disabled={pending || !datasets.length} onChange={(event) => setDataset(event.target.value)}>{datasets.length ? datasets.map((version) => <option key={version} value={version}>{version}</option>) : <option value="">No dataset available</option>}</select></label>
        <label className="field-control" htmlFor={`${id}-harness`}><span>Queue harness</span><select id={`${id}-harness`} value={harnessId} disabled={pending} aria-describedby={isCodex ? `${id}-codex` : undefined} onChange={(event) => setHarnessId(event.target.value)}><option value="">Choose a harness</option>{harnesses.map((harness) => <option key={harness.id} value={harness.id}>{harness.name}</option>)}<option value={CODEX_TRAINING_ID}>Codex (training)</option></select></label>
        <button className="button button--primary" type="submit" disabled={loading || !!error || pending || singleRunning || !ready || hasActive || !count || !validHarness}><ListOrdered size={16} aria-hidden="true" />Run full queue{count ? ` · ${count}` : ""}</button>
      </form>
      {isCodex ? <p id={`${id}-codex`} className="position-queue__hint">{!codexWorker?.online ? <>Windows worker offline. Start it with <code>.\scripts\start-codex-worker.ps1</code> to run a Codex queue.</> : codexWorker.active_run_id && !codexWorker.active_queue_id ? "The Windows worker is busy with a single-position run." : "Uses the Windows worker’s model and reasoning settings for every position. Keep the worker running; you can close this tab."}</p> : null}
      <p className="position-queue__hint">{singleRunning ? "The single-position run must finish before starting a queue." : hasActive ? "One queue is active. You can browse positions and traces while it runs." : `Runs every position in the ${setName(split).toLowerCase()} set, regardless of library filters. You can close this tab while it runs.`}</p>
      {error || commandError ? <div className="position-queue__error" role="alert"><span>{error || commandError}</span><button className="button button--secondary" type="button" onClick={() => { setCommandError(null); setRevision((value) => value + 1); }}><RefreshCw size={14} aria-hidden="true" />Refresh queue</button></div> : null}
      {loading ? <p role="status" className="position-queue__hint">Loading queues…</p> : null}
      {queues.length > 0 ? <section className="position-queue__retry" aria-labelledby={`${id}-retry-heading`}>
        <h3 id={`${id}-retry-heading`}>Retry a past queue</h3>
        <form className="position-queue__retry-form" onSubmit={(event) => { event.preventDefault(); void retryFailed(); }}>
          <label className="field-control" htmlFor={`${id}-retry-source`}><span>Past queue</span><select id={`${id}-retry-source`} value={retrySource?.id ?? ""} disabled={loading || pending || !retrySources.length} aria-describedby={`${id}-retry-source-hint`} onChange={(event) => { setRetrySourceId(event.target.value); setCommandError(null); }}>
            <option value="">{retrySources.length ? "Choose a queue to retry" : "No past queues with failed positions"}</option>
            {retrySources.map((item) => <option key={item.id} value={item.id}>{item.name || `${setName(item.split)} set`} · {item.failed} failed · {new Date(item.createdAt).toLocaleString()} · {item.id.slice(0, 8)}</option>)}
          </select></label>
          <button className="button button--secondary" type="submit" disabled={!retrySource || loading || !!error || pending || !!retryBlock} aria-describedby={`${id}-retry-source-hint ${id}-retry-hint`}><RotateCcw size={15} aria-hidden="true" />{retrying ? "Restarting failed positions…" : `Retry failed positions${retrySource ? ` · ${retrySource.failed}` : ""}`}</button>
        </form>
        <p id={`${id}-retry-source-hint`} className="position-queue__hint" aria-live="polite">{retrySource ? <><strong>{retrySource.name || `${setName(retrySource.split)} set`}</strong> · {retrySource.harnessName} · {modelName(retrySource.modelSelection)}<br />Failed positions restart in this same queue using its saved settings. Completed and skipped positions stay as they are. Earlier attempts remain in run history.</> : retrySources.length ? "Choose the queue whose failed positions you want to run again. This choice is separate from the results shown below." : "Finished or stopped queues with failed positions will appear here."}</p>
        <p id={`${id}-retry-hint`} className="position-queue__hint" role="status">{retryBlock}</p>
      </section> : null}
      {queues.length > 0 ? <label className="field-control position-queue__history" htmlFor={`${id}-history`}><span>Recent queues</span><select id={`${id}-history`} value={selectedId || queues[0].id} onChange={(event) => { setSelectedId(event.target.value); setFailedOnly(false); }}>{queues.map((q) => <option key={q.id} value={q.id}>{q.name ? `${q.name} · ` : ""}{setName(q.split)} · {q.harnessName} · {new Date(q.createdAt).toLocaleString()} · {q.status} · {q.id.slice(0, 8)}</option>)}</select></label> : null}
      {selected ? <div className="position-queue__progress">
        <p className="position-queue__id">{selected.retryOf ? "Retry queue run" : "Full queue run"} <code>{selected.id}</code></p>
        {selected.retryOf ? <p className="position-queue__id">Retry of {selected.retryOfName ? `${selected.retryOfName} · ` : ""}<code>{selected.retryOf}</code></p> : null}
        <header><div><h3><span>{selected.name || `${setName(selected.split)} set`}</span><span className={`run-status run-status--${selected.status}`}>{selected.status}</span></h3><p>{selected.name ? `${setName(selected.split)} set · ` : ""}{selected.harnessName} · {modelName(selected.modelSelection)} · {selected.datasetVersion}</p></div>{active(selected) ? <button className="button button--secondary" type="button" disabled={pending || selected.status === "stopping"} onClick={() => void stop()}><Square size={13} aria-hidden="true" />{selected.status === "stopping" ? "Stopping after current…" : "Stop after current"}</button> : null}</header>
        <div className="position-queue__counts" aria-live="polite"><strong>{selected.completed + selected.failed} / {selected.total} attempted</strong><span>{selected.completed} completed</span><button type="button" className={selected.failed ? "run-failure" : ""} disabled={!selected.failed} onClick={() => { setFailedOnly(true); setExpanded(true); }}>{selected.failed} failed</button><span>{selected.pending} waiting{selected.skipped ? ` · ${selected.skipped} skipped` : ""}</span></div>
        <progress aria-label="Queue progress" max={selected.total} value={selected.completed + selected.failed + selected.skipped} />
        {selected.modelSelection.modelId === "codex" && active(selected) && !current && !codexWorker?.online ? <p className="position-queue__hint" role="status">Waiting for the Windows Codex worker. Pending positions will resume when it reconnects.</p> : null}
        {current ? <div className="position-queue__current"><LoaderCircle className="spin" size={15} aria-hidden="true" /><span>Position {current.ordinal}: {positionsById.get(current.positionId)?.name ?? current.positionId}</span><button type="button" disabled={singleRunning} onClick={() => inspect(current)}>{current.runId ? "View live trace" : "View position"}</button></div> : null}
        {selected.status === "stopping" ? <p className="position-queue__hint">The current position will finish. Remaining positions will be marked skipped.</p> : null}
        <details className="position-queue__items" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
          <summary><ChevronRight size={15} aria-hidden="true" />Positions and results</summary>
          <label className="position-queue__filter"><input type="checkbox" checked={failedOnly} onChange={(event) => setFailedOnly(event.target.checked)} />Show failures only</label>
          <div className="position-queue__list" role="region" aria-label="Queue positions" tabIndex={0}>
            {selected.items.filter((item) => !failedOnly || item.status === "failed").map((item) => <div className="position-queue__item" key={item.ordinal}>
              <span className="position-queue__ordinal">{item.ordinal}</span>
              <div className="position-queue__item-copy"><strong>{positionsById.get(item.positionId)?.name ?? item.positionId}</strong><small>{tagLabel(item.phase)} · {tagLabel(item.positionType)}</small>{item.error ? <p className="run-failure">{tagLabel(item.failureStage ?? "execution")}: {item.error}</p> : null}</div>
              <div className="position-queue__outcome"><span className={`run-status run-status--${item.status}`}>{item.status}</span>{item.finalMoveUci ? <small><code>{item.finalMoveUci}</code>{item.classification ? ` · ${item.classification}` : ""}</small> : null}</div>
              <button type="button" disabled={singleRunning} onClick={() => inspect(item)}>{item.runId ? "View trace" : "View position"}</button>
            </div>)}
            {failedOnly && !selected.failed ? <p className="position-queue__hint">No failed positions in this queue.</p> : null}
          </div>
        </details>
      </div> : null}
    </section>
  );
}
