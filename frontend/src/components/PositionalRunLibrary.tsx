import { ChevronLeft, ChevronRight, RefreshCw, Search, Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { matchApi } from "../api/client";
import type { ModelRun, ModelRunFilterOptions, ModelRunFilters } from "../api/contracts";
import { RunDetail } from "./RunHistory";
import { tagLabel } from "./positionFilters";
import { DeleteRunDialog, type DeleteScope } from "./DeleteRunDialog";

const PAGE_SIZE = 30;
const emptyOptions: ModelRunFilterOptions = { datasets: [], models: [], harnesses: [], queues: [] };
const time = (value: string) => new Date(value).toLocaleString();
const message = (error: unknown) => error instanceof Error ? error.message : "Saved runs could not be loaded. Try again.";

export function PositionalRunLibrary({ active }: { active: boolean }) {
  const id = useId();
  const sectionRef = useRef<HTMLElement>(null);
  const [deleteTarget, setDeleteTarget] = useState<ModelRun | null>(null);
  const [draft, setDraft] = useState<ModelRunFilters>({});
  const [filters, setFilters] = useState<ModelRunFilters>({});
  const [options, setOptions] = useState(emptyOptions);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [runs, setRuns] = useState<ModelRun[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const offset = filters.offset ?? 0;

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    matchApi.getModelRunFilters().then((result) => {
      if (!cancelled) { setOptions(result); setOptionsError(null); }
    }).catch((caught: unknown) => { if (!cancelled) setOptionsError(message(caught)); });
    return () => { cancelled = true; };
  }, [active, revision]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const result = await matchApi.listModelRuns(filters);
        if (cancelled) return;
        if (result.items.length === 0 && (filters.offset ?? 0) > 0) {
          setFilters((current) => ({ ...current, offset: Math.max(0, Math.floor((result.total - 1) / PAGE_SIZE) * PAGE_SIZE) }));
          return;
        }
        setRuns(result.items);
        setTotal(result.total);
        setSelectedId((current) => result.items.some((run) => run.id === current) ? current : result.items[0]?.id ?? "");
        setError(null);
        if (result.items.some((run) => run.status === "running" || run.status === "queued")) {
          timer = setTimeout(() => void load(), 3000);
        }
      } catch (caught) {
        if (!cancelled) setError(message(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active, filters, revision]);

  const apply = (next: ModelRunFilters) => {
    setFilters(next);
    setSelectedId("");
    setLoading(true);
    setError(null);
  };
  const clear = () => { setDraft({}); apply({}); };
  const viewQueue = (queueTag: string) => {
    const next = { queueTag, offset: 0 };
    setDraft(next);
    apply(next);
  };
  const choose = (key: keyof ModelRunFilters, value: string) => setDraft((current) => ({ ...current, [key]: value }));
  const filtered = Object.entries(filters).some(([key, value]) => key !== "offset" && key !== "sort" && !!value);
  const refresh = () => { setLoading(true); setRevision((value) => value + 1); };
  const deleteRun = async (scope: DeleteScope) => {
    if (!deleteTarget) return;
    const queueTag = scope === "queue" ? deleteTarget.queueTag : null;
    if (queueTag) await matchApi.deletePositionQueue(queueTag);
    else await matchApi.deleteModelRun(deleteTarget.id);
    const removed = (run: ModelRun) => queueTag ? run.queueTag === queueTag : run.id === deleteTarget.id;
    setRuns((current) => current.filter((run) => !removed(run)));
    if (runs.some((run) => run.id === selectedId && removed(run))) setSelectedId("");
    if (queueTag) {
      setOptions((current) => ({ ...current, queues: current.queues.filter((queue) => queue.id !== queueTag) }));
      setDraft((current) => current.queueTag === queueTag ? { ...current, queueTag: "" } : current);
      setFilters((current) => current.queueTag === queueTag ? { ...current, queueTag: "", offset: 0 } : current);
    }
    refresh();
  };

  return (
    <section className="positional-run-library" ref={sectionRef} tabIndex={-1} aria-labelledby={`${id}-title`}>
      {deleteTarget ? <DeleteRunDialog recordId={deleteTarget.id} label={String(deleteTarget.config.harness_name ?? deleteTarget.harness)} queue={deleteTarget.queueTag ? { id: deleteTarget.queueTag, name: deleteTarget.queueName } : undefined} fallbackFocus={sectionRef} onDelete={deleteRun} onCancel={() => setDeleteTarget(null)} /> : null}
      <header className="run-history__header">
        <div><h2 id={`${id}-title`}>Positional runs</h2><p>Browse saved attempts. Select a run to inspect its position, engine analysis, and model passes.</p></div>
        <button type="button" onClick={refresh}><RefreshCw size={15} aria-hidden="true" />Refresh runs</button>
      </header>
      <form className="library-filters" onSubmit={(event) => { event.preventDefault(); apply({ ...draft, offset: 0 }); }}>
        <div className="library-filters__primary">
          <label className="field-control" htmlFor={`${id}-queue`}><span>Queue run</span>
            <select id={`${id}-queue`} value={draft.queueTag || draft.runSource || ""} onChange={(event) => {
              const value = event.target.value;
              setDraft((current) => ({ ...current, queueTag: value && value !== "single" && value !== "queue" ? value : "", runSource: value === "single" || value === "queue" ? value : "" }));
            }}>
              <option value="">All queues and single runs</option><option value="queue">All queue runs</option><option value="single">Single runs only</option>
              {filters.queueTag && !options.queues.some((queue) => queue.id === filters.queueTag) ? <option value={filters.queueTag}>Queue {filters.queueTag}</option> : null}
              {options.queues.map((queue) => <option key={queue.id} value={queue.id}>{queue.name ? `${queue.name} · ` : ""}{time(queue.createdAt)} · {queue.split === "train" ? "Training" : "Test"} · {queue.datasetVersion} · {queue.harnessName} · {queue.id.slice(0, 8)}</option>)}
            </select>
          </label>
          <label className="field-control" htmlFor={`${id}-set`}><span>Position set</span><select id={`${id}-set`} value={draft.split ?? ""} onChange={(event) => choose("split", event.target.value)}><option value="">All sets</option><option value="train">Training</option><option value="test">Test</option></select></label>
          <label className="field-control" htmlFor={`${id}-analysis`}><span>Engine analysis</span><select id={`${id}-analysis`} value={draft.analysis ?? ""} onChange={(event) => choose("analysis", event.target.value)}><option value="">Any analysis</option><option value="completed">Evaluated</option><option value="failed">Evaluation failed</option><option value="missing">Not evaluated</option></select></label>
          <label className="field-control" htmlFor={`${id}-grade`}><span>Move grade</span><select id={`${id}-grade`} value={draft.classification ?? ""} onChange={(event) => choose("classification", event.target.value)}><option value="">All grades</option>{["best", "excellent", "good", "inaccuracy", "mistake", "blunder"].map((grade) => <option value={grade} key={grade}>{tagLabel(grade)}</option>)}</select></label>
        </div>
        <details className="library-filters__more">
          <summary>More filters · dataset, harness, model, status</summary>
          <div className="library-filters__primary">
            <label className="field-control" htmlFor={`${id}-dataset`}><span>Dataset</span><select id={`${id}-dataset`} value={draft.datasetVersion ?? ""} onChange={(event) => choose("datasetVersion", event.target.value)}><option value="">All datasets</option>{options.datasets.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="field-control" htmlFor={`${id}-harness`}><span>Harness</span><select id={`${id}-harness`} value={draft.harness ?? ""} onChange={(event) => choose("harness", event.target.value)}><option value="">All harnesses</option>{options.harnesses.map((harness) => <option key={harness.id} value={harness.id}>{harness.name}</option>)}</select></label>
            <label className="field-control" htmlFor={`${id}-model`}><span>Model</span><select id={`${id}-model`} value={draft.model ?? ""} onChange={(event) => choose("model", event.target.value)}><option value="">All models</option>{options.models.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="field-control" htmlFor={`${id}-status`}><span>Run status</span><select id={`${id}-status`} value={draft.status ?? ""} onChange={(event) => choose("status", event.target.value)}><option value="">All statuses</option>{["completed", "failed", "running", "queued", "skipped"].map((value) => <option key={value} value={value}>{tagLabel(value)}</option>)}</select></label>
          </div>
        </details>
        <div className="library-filters__actions">
          <label className="search-control"><Search size={16} aria-hidden="true" /><span className="sr-only">Search positional runs</span><input value={draft.query ?? ""} maxLength={240} placeholder="Search queue name, run ID, position, or model" onChange={(event) => choose("query", event.target.value)} /></label>
          <button className="button button--primary" type="submit">Apply filters</button>
          <button className="button button--secondary" type="button" onClick={clear}>Clear filters</button>
        </div>
      </form>
      {optionsError ? <div className="library-options-error" role="alert"><span>Some filter choices could not be loaded. {optionsError}</span><button className="button button--secondary" type="button" onClick={refresh}>Retry filters</button></div> : null}
      <div className="library-results-bar">
        <p role="status">{loading ? "Loading saved runs…" : `${total} ${total === 1 ? "run" : "runs"}${filtered ? " matching filters" : " recorded"}`}</p>
        <label className="field-control" htmlFor={`${id}-sort`}><span>Order</span><select id={`${id}-sort`} value={filters.sort ?? "newest"} onChange={(event) => { const sort = event.target.value as "newest" | "oldest"; setDraft((current) => ({ ...current, sort })); apply({ ...filters, sort, offset: 0 }); }}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
      </div>
      {loading ? <div className="run-history__state" role="status">Loading saved attempts and results…</div> : error ? <div className="run-history__state" role="alert"><h3>Run history unavailable</h3><p>{error}</p><button type="button" onClick={refresh}>Retry history</button></div> : runs.length === 0 ? <div className="run-history__state"><h3>{filtered ? "No runs match these filters" : "No positional runs yet"}</h3><p>{filtered ? "Broaden the queue, set, or analysis filters to see more attempts." : "Run a position or a full queue in Positional testing. Saved attempts will appear here."}</p>{filtered ? <button type="button" onClick={clear}>Clear filters</button> : null}</div> : (
        <div className="library-run-workspace">
          <aside className="run-index" aria-label="Saved positional runs">
            <div className="library-run-index" tabIndex={0} role="region" aria-label="Browse positional runs">
              {runs.map((run) => <div className={`library-run-item${selectedId === run.id ? " library-run-item--selected" : ""}`} key={run.id}><button type="button" className={`library-run-row${selectedId === run.id ? " library-run-row--selected" : ""}`} aria-pressed={selectedId === run.id} onClick={() => setSelectedId(run.id)}>
                <span className="library-run-row__title"><strong>{String(run.config.harness_name ?? run.harness)}</strong><span className={`run-status run-status--${run.status}`}>{run.status}</span></span>
                <span>{run.phase ? tagLabel(run.phase) : "Position"} · {run.split === "train" ? "Training" : run.split === "test" ? "Test" : "Unspecified set"} · {run.datasetVersion}</span>
                <span>{run.model}</span>
                <span className="library-run-row__result"><strong>{run.finalMoveUci ?? (run.status === "running" || run.status === "queued" ? "Awaiting move" : "No move submitted")}</strong><span>{run.classification ? tagLabel(run.classification) : run.analysisStatus === "failed" ? "Evaluation failed" : "Not evaluated"}{run.cpLoss !== null ? ` · ${run.cpLoss} cp` : ""}</span></span>
                <time dateTime={run.createdAt}>{time(run.createdAt)}</time>
                <code>{run.id}</code>
                {run.queueTag ? <small title={`Full queue run ${run.queueTag}`}>{run.queueName || `Queue ${run.queueTag.slice(0, 8)}`}{typeof run.config.queue_ordinal === "number" ? ` · position ${run.config.queue_ordinal}` : ""}</small> : <small>Single run</small>}
              </button><button className="icon-button icon-button--delete" type="button" aria-label={`Delete run ${run.id}`} title="Delete run" onClick={() => setDeleteTarget(run)}><Trash2 size={16} aria-hidden="true" /></button></div>)}
            </div>
            <div className="position-pagination">
              <button type="button" aria-label="Previous positional runs" disabled={offset === 0} onClick={() => apply({ ...filters, offset: Math.max(0, offset - PAGE_SIZE) })}><ChevronLeft size={16} aria-hidden="true" /></button>
              <span>{offset + 1}–{offset + runs.length} of {total}</span>
              <button type="button" aria-label="Next positional runs" disabled={offset + runs.length >= total} onClick={() => apply({ ...filters, offset: offset + PAGE_SIZE })}><ChevronRight size={16} aria-hidden="true" /></button>
            </div>
          </aside>
          {selectedId && active ? <RunDetail key={selectedId} runId={selectedId} refresh={revision} onQueueFilter={viewQueue} visualize /> : null}
        </div>
      )}
    </section>
  );
}
