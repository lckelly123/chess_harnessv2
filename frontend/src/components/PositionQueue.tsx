import { ChevronRight, ListOrdered, LoaderCircle, RefreshCw, Square } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import { matchApi } from "../api/client";
import type { HarnessVersion, ModelSelection, PositionalTestPosition, PositionQueueDetail, PositionQueueItem, PositionQueueSummary } from "../api/contracts";
import { tagLabel } from "./positionFilters";

const active = (queue: PositionQueueSummary) => ["queued", "running", "stopping"].includes(queue.status);
const modelName = (selection: ModelSelection) => selection.modelId === "gpt-terra" ? "GPT Terra" : "Qwen";
const message = (caught: unknown) => caught instanceof Error ? caught.message : "Queue unavailable. Retry to reconnect.";
const setName = (split: string) => split === "train" ? "Training" : "Test";

interface PositionQueueProps {
  positions: PositionalTestPosition[];
  harnesses: HarnessVersion[];
  modelSelection: ModelSelection;
  singleRunning: boolean;
  onActiveChange: (active: boolean) => void;
  onInspect: (positionId: string, runId: string | null) => void;
}

export function PositionQueue({ positions, harnesses, modelSelection, singleRunning, onActiveChange, onInspect }: PositionQueueProps) {
  const id = useId();
  const [split, setSplit] = useState<"train" | "test">("train");
  const [dataset, setDataset] = useState("");
  const [harnessId, setHarnessId] = useState("");
  const [queues, setQueues] = useState<PositionQueueSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
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

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const result = await matchApi.listPositionQueues();
        const nextId = selectedId || result.items[0]?.id;
        const detail = nextId ? await matchApi.getPositionQueue(nextId) : null;
        if (cancelled) return;
        setQueues(result.items);
        setQueue(detail);
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
    if (!count || !harnessId || hasActive || singleRunning || pending || error) return;
    setPending(true);
    setCommandError(null);
    try {
      const result = await matchApi.createPositionQueue({ split, datasetVersion, harnessId, modelSelection });
      setQueues((previous) => [result, ...previous.filter((q) => q.id !== result.id)]);
      setQueue(result);
      setSelectedId(result.id);
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

  const inspect = (item: PositionQueueItem) => onInspect(item.positionId, item.runId);
  return (
    <section className="position-queue" aria-labelledby={`${id}-heading`}>
      <header className="position-queue__heading">
        <div><h2 id={`${id}-heading`}>Run a full set</h2><p>One position at a time, including evaluation. Failures are saved and the queue continues.</p></div>
        <span className="position-queue__model">New queue: <strong>{modelName(modelSelection)}</strong></span>
      </header>
      <form className="position-queue__form" onSubmit={(event) => { event.preventDefault(); void start(); }}>
        <label className="field-control" htmlFor={`${id}-set`}><span>Position set</span><select id={`${id}-set`} value={split} disabled={pending} onChange={(event) => setSplit(event.target.value as "train" | "test")}><option value="train">Training</option><option value="test">Test</option></select></label>
        <label className="field-control" htmlFor={`${id}-dataset`}><span>Dataset</span><select id={`${id}-dataset`} value={datasetVersion} disabled={pending || !datasets.length} onChange={(event) => setDataset(event.target.value)}>{datasets.length ? datasets.map((version) => <option key={version} value={version}>{version}</option>) : <option value="">No dataset available</option>}</select></label>
        <label className="field-control" htmlFor={`${id}-harness`}><span>Queue harness</span><select id={`${id}-harness`} value={harnessId} disabled={pending || !harnesses.length} onChange={(event) => setHarnessId(event.target.value)}><option value="">Choose a harness</option>{harnesses.map((harness) => <option key={harness.id} value={harness.id}>{harness.name}</option>)}</select></label>
        <button className="button button--primary" type="submit" disabled={loading || !!error || pending || singleRunning || hasActive || !count || !harnesses.some((h) => h.id === harnessId)}><ListOrdered size={16} aria-hidden="true" />Run full queue{count ? ` · ${count}` : ""}</button>
      </form>
      <p className="position-queue__hint">{singleRunning ? "The single-position run must finish before starting a queue." : hasActive ? "One queue is active. You can browse positions and traces while it runs." : `Runs every position in the ${setName(split).toLowerCase()} set, regardless of library filters. You can close this tab while it runs.`}</p>
      {error || commandError ? <div className="position-queue__error" role="alert"><span>{error || commandError}</span><button className="button button--secondary" type="button" onClick={() => { setCommandError(null); setRevision((value) => value + 1); }}><RefreshCw size={14} aria-hidden="true" />Refresh queue</button></div> : null}
      {loading ? <p role="status" className="position-queue__hint">Loading queues…</p> : null}
      {queues.length > 0 ? <label className="field-control position-queue__history" htmlFor={`${id}-history`}><span>Recent queues</span><select id={`${id}-history`} value={selectedId || queues[0].id} onChange={(event) => { setSelectedId(event.target.value); setFailedOnly(false); }}>{queues.map((q) => <option key={q.id} value={q.id}>{setName(q.split)} · {q.harnessName} · {new Date(q.createdAt).toLocaleString()} · {q.status}</option>)}</select></label> : null}
      {selected ? <div className="position-queue__progress">
        <header><div><h3>{setName(selected.split)} set <span className={`run-status run-status--${selected.status}`}>{selected.status}</span></h3><p>{selected.harnessName} · {modelName(selected.modelSelection)} · {selected.datasetVersion}</p></div>{active(selected) ? <button className="button button--secondary" type="button" disabled={pending || selected.status === "stopping"} onClick={() => void stop()}><Square size={13} aria-hidden="true" />{selected.status === "stopping" ? "Stopping after current…" : "Stop after current"}</button> : null}</header>
        <div className="position-queue__counts" aria-live="polite"><strong>{selected.completed + selected.failed} / {selected.total} attempted</strong><span>{selected.completed} completed</span><button type="button" className={selected.failed ? "run-failure" : ""} disabled={!selected.failed} onClick={() => { setFailedOnly(true); setExpanded(true); }}>{selected.failed} failed</button><span>{selected.pending} waiting{selected.skipped ? ` · ${selected.skipped} skipped` : ""}</span></div>
        <progress aria-label="Queue progress" max={selected.total} value={selected.completed + selected.failed + selected.skipped} />
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
