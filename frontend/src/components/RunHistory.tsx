import { ChevronLeft, ChevronRight, LoaderCircle, RefreshCw, Search } from "lucide-react";
import { useContext, useEffect, useId, useRef, useState } from "react";
import { matchApi } from "../api/client";
import type { ModelRun, ModelRunDetail, ModelRunFilters, ModelRunPass, PassToolCall } from "../api/contracts";
import { Chessboard } from "./Chessboard";
import { tagLabel } from "./positionFilters";
import { ModelExchangeContext } from "./modelExchangeContext";

const UUID_PATTERN = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const PAGE_SIZE = 30;
const time = (value: string) => new Date(value).toLocaleString();
const errorMessage = (value: unknown) => value instanceof Error ? value.message : "Run history could not be loaded.";
const json = (value: unknown) => JSON.stringify(value, null, 2);

function ToolCall({ call, running }: { call: PassToolCall; running: boolean }) {
  const outcome = call.rolled_back ? "Rolled back" : call.error ? "Rejected" : !call.executed ? running ? "Pending" : "Not executed" : "Returned";
  return (
    <details className="run-tool">
      <summary><span><ChevronRight size={13} aria-hidden="true" />{call.tool_name || "Unknown tool"}</span><small className={call.error ? "run-failure" : ""}>{outcome}</small></summary>
      {call.error ? <p className="run-failure">{call.error}</p> : null}
      <div className="run-tool__payload"><strong>Arguments</strong><pre>{json(call.arguments)}</pre></div>
      {call.result !== null ? <div className="run-tool__payload"><strong>Result</strong><pre>{json(call.result)}</pre></div> : null}
      {call.board_context ? <div className="run-tool__payload"><strong>Board context</strong><pre>{json(call.board_context)}</pre></div> : null}
      {call.call_id ? <p className="run-tool__id">Call {call.call_id}</p> : null}
    </details>
  );
}

function Pass({ pass }: { pass: ModelRunPass }) {
  const openExchange = useContext(ModelExchangeContext);
  const [expanding, setExpanding] = useState(false);
  const [expandError, setExpandError] = useState<string | null>(null);
  const expand = async () => {
    if (!openExchange || expanding) return;
    setExpanding(true);
    setExpandError(null);
    try { await openExchange(pass.runId, pass.passNumber); }
    catch (caught) { setExpandError(errorMessage(caught)); }
    finally { setExpanding(false); }
  };
  return (
    <article className="run-pass" aria-label={`Pass ${pass.passNumber}`}>
      <header><div><h4>Pass {pass.passNumber}</h4><span>{pass.phase} · {pass.toolCalls.length} tool {pass.toolCalls.length === 1 ? "call" : "calls"}</span></div><div className="run-pass__actions"><span className={`run-status run-status--${pass.status}`}>{pass.status}</span><button type="button" disabled={!pass.hasModelExchange || !openExchange || expanding} title={pass.hasModelExchange ? "Read model input and output as Markdown. Back or Escape returns to this pass." : "Model input/output was not recorded for this pass."} aria-busy={expanding} onClick={() => void expand()}>{expanding ? "Opening…" : "Expand"}</button></div></header>
      {expandError ? <p className="run-failure" role="alert">{expandError} Try Expand again.</p> : null}
      <p className="run-pass__time">{time(pass.startedAt)}</p>
      <h5>Working notes</h5>
      <p className={pass.workingNotes ? "run-pass__notes" : "run-muted"}>{pass.workingNotes || "No working notes emitted in this pass."}</p>
      {pass.error ? <p className="run-failure">{pass.error}</p> : null}
      {pass.toolCalls.length > 0 ? <div className="run-pass__tools">{pass.toolCalls.map((call, index) => <ToolCall key={index} call={call} running={pass.status === "running"} />)}</div> : null}
    </article>
  );
}

export function RunDetail({ runId, refresh, onQueueFilter, visualize = false }: { runId: string; refresh: number; onQueueFilter: (queueTag: string) => void; visualize?: boolean }) {
  const [run, setRun] = useState<ModelRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [flipped, setFlipped] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const result = await matchApi.getModelRun(runId);
        if (cancelled) return;
        setRun(result);
        setError(null);
        if ((result.status === "running" || result.status === "queued")) timer = setTimeout(() => void load(), 2000);
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught));
      }
    };
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [runId, retry, refresh]);

  if (error) return <div className="run-history__state" role="alert"><p>{error}</p><button type="button" onClick={() => setRetry(retry + 1)}>Retry run</button></div>;
  if (!run) return <div className="run-history__state" role="status"><LoaderCircle className="spin" size={16} aria-hidden="true" /> Loading run…</div>;
  return (
    <section className="run-detail" aria-label="Selected run">
      <header className="run-detail__header">
        <div><h3>{String(run.config.harness_name ?? run.harness)}</h3><p>{run.model} · {time(run.startedAt ?? run.createdAt)}</p></div>
        <span className={`run-status run-status--${run.status}`}>{run.status}</span>
      </header>
      {run.queueTag ? <div className="run-queue-origin"><span>{run.queueName ? <strong>{run.queueName}</strong> : null}Full queue run <code>{run.queueTag}</code></span><button type="button" onClick={() => onQueueFilter(run.queueTag!)}>View queue runs</button></div> : null}
      <div className={visualize ? "run-evidence" : undefined}>
      {visualize ? <div className="run-evidence__board">
        {run.positionFen ? <>
          <div className="run-evidence__position"><h3>{run.phase ? tagLabel(run.phase) : "Saved position"} · move {run.positionFen.split(" ")[5]}</h3><p>{run.split === "train" ? "Training" : run.split === "test" ? "Test" : "Unknown set"} · {run.datasetVersion}{run.positionType ? ` · ${tagLabel(run.positionType)}` : ""}</p></div>
          <Chessboard label={run.finalMoveUci ? `Saved position before proposed move ${run.finalMoveUci}` : "Saved position before the agent's move"} position={{ fen: run.positionFen, ply: 0, san: "", player: null, fromSquare: run.finalMoveUci?.slice(0, 2) ?? null, toSquare: run.finalMoveUci?.slice(2, 4) ?? null }} flipped={flipped} />
          <div className="run-evidence__caption"><span>{run.positionFen.split(" ")[1] === "w" ? "White" : "Black"} to move · {flipped ? "Black" : "White"} perspective</span><button type="button" onClick={() => setFlipped((value) => !value)}>Flip board</button></div>
          <p className="run-evidence__note">{run.finalMoveUci ? "Highlighted squares show the proposed move on the saved position." : "The saved position before the agent's turn."}</p>
        </> : <p className="run-evidence__note">The saved board is unavailable for this run. Its recorded results and trace are below.</p>}
      </div> : null}
      <div className="run-evidence__summary">
      <dl className="run-outcome">
        <div><dt>Chosen move</dt><dd className="run-outcome__move">{run.finalMoveUci ?? ((run.status === "running" || run.status === "queued") ? "Awaiting move" : "No move submitted")}</dd></div>
        <div><dt>Stockfish evaluation</dt><dd>{run.classification ?? (run.analysisStatus === "failed" || run.evaluation?.status === "failed" ? "Evaluation failed" : "Not evaluated")}</dd><small>{run.cpLoss !== null ? `${run.cpLoss} cp loss` : "No score recorded"}</small></div>
        {visualize && run.expectedPointsLoss !== null ? <div><dt>Expected points loss</dt><dd>{(run.expectedPointsLoss * 100).toFixed(1)}%</dd></div> : null}
        {visualize && run.evaluation?.engine_name ? <div><dt>Engine</dt><dd>{String(run.evaluation.engine_name)}</dd>{run.evaluation.depth != null ? <small>Depth {String(run.evaluation.depth)}</small> : null}</div> : null}
      </dl>
      {visualize && run.betterMoves ? <div className="run-better-moves"><h4>Better moves</h4><p>{run.betterMoves.length ? run.betterMoves.map((move) => String(move.san ?? move.uci ?? move.move_uci ?? "")).filter(Boolean).join(" · ") || "See the saved evaluation in Run details." : "No strictly better moves recorded."}</p></div> : null}
      <details className="run-metadata"><summary>Run details</summary><dl><div><dt>Position ID</dt><dd>{run.positionId}</dd></div><div><dt>Run ID</dt><dd>{run.id}</dd></div></dl><pre>{json(run.config)}</pre>{run.evaluation ? <pre>{json(run.evaluation)}</pre> : null}</details>
      {run.error ? <p className="run-detail__error run-failure">{run.error}</p> : null}
      </div>
      </div>
      <div className="run-passes-heading"><h3>Model passes</h3><span>{run.passes.length} recorded</span></div>
      <div className="run-passes" key={run.id} tabIndex={0} role="region" aria-label="Model pass timeline">
        {run.passes.length ? run.passes.map((pass) => <Pass key={pass.passNumber} pass={pass} />) : <p className="run-history__state">{run.status === "queued" ? "Queued. Model passes will appear when this position starts." : run.status === "running" ? "Waiting for the first model pass…" : "No model passes were recorded for this run."}</p>}
      </div>
    </section>
  );
}

interface RunHistoryProps {
  positionId: string;
  preferredRunId?: string;
  revision: number;
  running: boolean;
}

export function RunHistory({ positionId, preferredRunId, revision, running }: RunHistoryProps) {
  const id = useId();
  const [positionFilter, setPositionFilter] = useState(positionId);
  const [runFilter, setRunFilter] = useState(preferredRunId ?? "");
  const [queueFilter, setQueueFilter] = useState("");
  const [filters, setFilters] = useState<ModelRunFilters>({ positionId, runId: preferredRunId, offset: 0 });
  const [runs, setRuns] = useState<ModelRun[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const preferredApplied = useRef<string | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const result = await matchApi.listModelRuns(filters);
        if (cancelled) return;
        setRuns(result.items);
        setTotal(result.total);
        setError(null);
        const prefer = preferredRunId && preferredApplied.current !== preferredRunId && result.items.some((run) => run.id === preferredRunId);
        if (prefer) preferredApplied.current = preferredRunId;
        setSelectedId((current) => {
          if (prefer) return preferredRunId;
          return result.items.some((run) => run.id === current) ? current : result.items[0]?.id ?? "";
        });
        if (running || result.items.some((run) => run.status === "running")) timer = setTimeout(() => void load(), 2000);
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [filters, refresh, preferredRunId, revision, running]);

  const apply = (next: ModelRunFilters) => {
    setLoading(true);
    setError(null);
    setSelectedId("");
    setFilters(next);
  };
  const viewQueue = (queueTag: string) => {
    setPositionFilter("");
    setRunFilter("");
    setQueueFilter(queueTag);
    apply({ queueTag, offset: 0 });
  };
  return (
    <section className="run-history" id="positional-run-history" aria-labelledby={`${id}-title`} tabIndex={-1}>
      <header className="run-history__header"><div><h2 id={`${id}-title`}>Run history</h2><p>Review the chosen move, working notes, and tool results from each attempt.</p></div><button type="button" aria-label="Refresh run history" onClick={() => setRefresh(refresh + 1)}><RefreshCw size={15} aria-hidden="true" /> Refresh</button></header>
      <form className="run-history__filters" onSubmit={(event) => { event.preventDefault(); apply({ positionId: positionFilter.trim(), runId: runFilter.trim(), queueTag: queueFilter.trim(), offset: 0 }); }}>
        <label className="field-control" htmlFor={`${id}-position`}><span>Position ID</span><input id={`${id}-position`} value={positionFilter} pattern={UUID_PATTERN} placeholder="All positions" onChange={(event) => setPositionFilter(event.target.value)} /></label>
        <label className="field-control" htmlFor={`${id}-run`}><span>Run ID</span><input id={`${id}-run`} value={runFilter} pattern={UUID_PATTERN} placeholder="All runs for this position" onChange={(event) => setRunFilter(event.target.value)} /></label>
        <label className="field-control" htmlFor={`${id}-queue`}><span>Queue tag</span><input id={`${id}-queue`} value={queueFilter} pattern={UUID_PATTERN} placeholder="All queues" onChange={(event) => setQueueFilter(event.target.value)} /></label>
        <button type="submit"><Search size={15} aria-hidden="true" /> Filter runs</button>
        <button type="button" onClick={() => { setPositionFilter(""); setRunFilter(""); setQueueFilter(""); apply({ offset: 0 }); }}>All runs</button>
      </form>
      {loading ? <div className="run-history__state" role="status">Loading run history…</div> : error ? <div className="run-history__state" role="alert"><p>{error}</p><button type="button" onClick={() => { setLoading(true); setRefresh(refresh + 1); }}>Retry history</button></div> : runs.length === 0 ? <div className="run-history__state"><h3>No runs found</h3><p>{filters.runId || filters.queueTag ? "Check the position, run, and queue IDs, or choose All runs." : "Run a positional test to start recording model passes here."}</p></div> : (
        <div className="run-history__workspace">
          <aside className="run-index" aria-label="Saved model runs">
            <p className="run-index__count">{total} {total === 1 ? "run" : "runs"}{running ? " · updating live" : ""}</p>
            <div className="run-index__list">{runs.map((run) => <button type="button" className={`run-row${selectedId === run.id ? " run-row--selected" : ""}`} key={run.id} aria-pressed={selectedId === run.id} onClick={() => setSelectedId(run.id)}><span><strong>{String(run.config.harness_name ?? run.harness)}</strong><small className={`run-status run-status--${run.status}`}>{run.status}</small></span><span>{run.model}</span><code>{run.id}</code>{run.queueTag ? <span title={`Full queue run ${run.queueTag}`}>{run.queueName || "Full queue run"} · <code>{run.queueTag.slice(0, 8)}</code></span> : null}<small>{time(run.startedAt ?? run.createdAt)}{run.finalMoveUci ? ` · ${run.finalMoveUci}` : ""}</small></button>)}</div>
            {total > PAGE_SIZE ? <div className="position-pagination"><button type="button" aria-label="Previous runs" disabled={!filters.offset} onClick={() => apply({ ...filters, offset: (filters.offset ?? 0) - PAGE_SIZE })}><ChevronLeft size={16} /></button><span>{(filters.offset ?? 0) + 1}–{Math.min(total, (filters.offset ?? 0) + PAGE_SIZE)} of {total}</span><button type="button" aria-label="Next runs" disabled={(filters.offset ?? 0) + PAGE_SIZE >= total} onClick={() => apply({ ...filters, offset: (filters.offset ?? 0) + PAGE_SIZE })}><ChevronRight size={16} /></button></div> : null}
          </aside>
          {selectedId ? <RunDetail key={selectedId} runId={selectedId} refresh={refresh + revision} onQueueFilter={viewQueue} /> : null}
        </div>
      )}
    </section>
  );
}
