import {
  AlertTriangle,
  Check,
  Crosshair,
  LoaderCircle,
  Play,
  RotateCcw,
  Square,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ApiError, matchApi } from "../api/client";
import { CODEX_TRAINING_ID, codexApi, type CodexJob, type CodexWorkerStatus } from "../api/codex";
import { CodexTrainingChoice } from "./CodexTrainingChoice";
import type {
  HarnessVersion,
  ModelSelection,
  PositionRecord,
  PositionalTestPosition,
  PositionalTestRun,
} from "../api/contracts";
import { Chessboard } from "./Chessboard";
import { PositionLibrary, PositionTags } from "./PositionLibrary";
import { tagLabel } from "./positionFilters";
import { RunHistory } from "./RunHistory";
import { PositionQueue } from "./PositionQueue";

const POSITIONAL_HARNESSES = [
  { id: "baseline-direct-submit-langgraph-v1", name: "Baseline" },
  { id: "agent-player-1-langgraph-v1", name: "legacy" },
  { id: "agent-player-2-langgraph-v1", name: "chess_harness" },
  { id: "agent-player-3-langgraph-v1", name: "chess_charness_alt" },
];

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

interface PositionalTestingProps {
  modelSelection: ModelSelection;
  modelReady: boolean;
  running: boolean;
  onRunningChange: (running: boolean) => void;
}

export function PositionalTesting({ modelSelection, modelReady, running, onRunningChange }: PositionalTestingProps) {
  const [positions, setPositions] = useState<PositionalTestPosition[]>([]);
  const [harnesses, setHarnesses] = useState<HarnessVersion[]>([]);
  const [selectedPositionId, setSelectedPositionId] = useState("");
  const [selectedHarnessId, setSelectedHarnessId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [harnessLoading, setHarnessLoading] = useState(true);
  const [harnessError, setHarnessError] = useState<string | null>(null);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [runError, setRunError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<PositionalTestRun | null>(null);
  const [queueActive, setQueueActive] = useState(false);
  const [inspectedRunId, setInspectedRunId] = useState<string | undefined>();
  const [codexWorker, setCodexWorker] = useState<CodexWorkerStatus | null>(null);
  const [codexRunId, setCodexRunId] = useState<string | null>(null);
  const [codexJob, setCodexJob] = useState<CodexJob | null>(null);
  const [codexConnectionError, setCodexConnectionError] = useState<string | null>(null);
  const isCodex = selectedHarnessId === CODEX_TRAINING_ID;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const worker = await codexApi.worker();
        if (cancelled) return;
        setCodexWorker(worker);
        if (worker.active_run_id) setCodexRunId((current) => current ?? worker.active_run_id);
      } catch {
        if (!cancelled) setCodexWorker(null);
      } finally {
        if (!cancelled) timer = setTimeout(() => void poll(), 3000);
      }
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!codexRunId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const job = await codexApi.job(codexRunId);
        if (cancelled) return;
        setCodexJob(job);
        setCodexConnectionError(null);
        setSelectedPositionId(job.position_id);
        setSelectedHarnessId(CODEX_TRAINING_ID);
        setInspectedRunId(job.run_id);
        if (["completed", "failed", "cancelled"].includes(job.status)) {
          setRunResult(job.result);
          setRunError(job.error);
          setCodexRunId(null);
          setHistoryRevision((value) => value + 1);
          onRunningChange(false);
          return;
        }
        onRunningChange(true);
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.status === 404) {
          setRunError("The live Codex session ended after a backend restart. Open run history for the saved passes.");
          setCodexRunId(null);
          setHistoryRevision((value) => value + 1);
          onRunningChange(false);
          return;
        }
        setCodexConnectionError("Connection interrupted. Reconnecting to the Codex run…");
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 1500);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [codexRunId, onRunningChange]);

  useEffect(() => {
    let cancelled = false;
    matchApi.listPositionalTestPositions().then((response) => {
      if (cancelled) return;
      setPositions(response.items);
      setSelectedPositionId((current) =>
        response.items.some((position) => position.id === current) ? current : response.items[0]?.id ?? "",
      );
    }).catch((caught: unknown) => {
      if (!cancelled) {
        setError(caught instanceof Error ? caught.message : "The position library could not be loaded.");
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    matchApi.listHarnesses().then((response) => {
      if (cancelled) return;
      setHarnesses(response);
    }).catch((caught: unknown) => {
      if (!cancelled) {
        setHarnessError(caught instanceof Error ? caught.message : "Harness choices could not be loaded.");
      }
    }).finally(() => {
      if (!cancelled) setHarnessLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  const selectedPosition = useMemo(
    () => loading || error ? null : positions.find((position) => position.id === selectedPositionId) ?? null,
    [positions, selectedPositionId, loading, error],
  );

  const availableHarnesses = useMemo(() => {
    const byId = new Map(harnesses.map((harness) => [harness.id, harness]));
    return POSITIONAL_HARNESSES.flatMap(({ id }) => {
      const harness = byId.get(id);
      return harness ? [harness] : [];
    });
  }, [harnesses]);

  const missingHarnesses = POSITIONAL_HARNESSES.filter(
    ({ id }) => !availableHarnesses.some((harness) => harness.id === id),
  );

  const selectedHarness = isCodex ? { id: CODEX_TRAINING_ID, name: "Codex (training)" } : availableHarnesses.find(
    (harness) => harness.id === selectedHarnessId,
  );

  const boardPosition = useMemo<PositionRecord | null>(() => {
    if (!selectedPosition) return null;
    if (!runResult || runResult.positionId !== selectedPosition.id) {
      return selectedPosition.position;
    }
    return {
      ...selectedPosition.position,
      fromSquare: runResult.move.fromSquare,
      toSquare: runResult.move.toSquare,
    };
  }, [runResult, selectedPosition]);

  const clearRun = () => {
    setInspectedRunId(undefined);
    setRunError(null);
    setRunResult(null);
    setCodexJob(null);
    setCodexConnectionError(null);
  };

  const choosePosition = (positionId: string) => {
    setSelectedPositionId(positionId);
    setSelectedHarnessId("");
    clearRun();
  };

  const chooseHarness = (harnessId: string) => {
    setSelectedHarnessId(harnessId);
    clearRun();
  };

  const runOnce = async () => {
    if (!selectedPosition || !selectedHarness || running || queueActive || !(isCodex ? codexWorker?.online : modelReady)) return;
    onRunningChange(true);
    setRunError(null);
    setRunResult(null);
    if (isCodex) {
      setCodexJob(null);
      try {
        const job = await codexApi.start(selectedPosition.id);
        setCodexJob(job);
        setCodexRunId(job.run_id);
        setInspectedRunId(job.run_id);
        setHistoryRevision((value) => value + 1);
      } catch (caught) {
        setRunError(caught instanceof Error ? caught.message : "Codex could not be started.");
        onRunningChange(false);
      }
      return;
    }
    try {
      const result = await matchApi.runPositionalTest({
        positionId: selectedPosition.id,
        harnessId: selectedHarness.id,
        modelSelection,
      });
      setRunResult(result);
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : "The positional test could not be completed.");
    } finally {
      setHistoryRevision((value) => value + 1);
      onRunningChange(false);
    }
  };

  const stopCodex = async () => {
    if (!codexRunId) return;
    try { setCodexJob(await codexApi.stop(codexRunId)); }
    catch (caught) { setCodexConnectionError(caught instanceof Error ? caught.message : "Could not stop Codex. Try Stop again."); }
  };

  const retryPositions = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await matchApi.listPositionalTestPositions();
      setPositions(response.items);
      if (!response.items.some((position) => position.id === selectedPositionId)) {
        setSelectedPositionId("");
        setSelectedHarnessId("");
        clearRun();
      }
      return response.items;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The position library could not be loaded.");
      return null;
    } finally {
      setLoading(false);
    }
  };

  const retryHarnesses = async () => {
    setHarnessLoading(true);
    setHarnessError(null);
    try {
      const response = await matchApi.listHarnesses();
      setHarnesses(response);
      if (selectedHarnessId !== CODEX_TRAINING_ID && !response.some((harness) => harness.id === selectedHarnessId)) {
        setSelectedHarnessId("");
        clearRun();
      }
    } catch (caught) {
      setHarnessError(caught instanceof Error ? caught.message : "Harness choices could not be loaded.");
    } finally {
      setHarnessLoading(false);
    }
  };

  return (
    <section className="positional-testing" aria-label="Positional testing workspace">
      <header className="positional-heading">
        <p>Run a training or test set, or inspect one position and its model traces.</p>
        <a href="#positional-run-history">View run history</a>
      </header>

      <PositionQueue positions={positions} harnesses={availableHarnesses} modelSelection={modelSelection} modelReady={modelReady} singleRunning={running} onActiveChange={setQueueActive} onInspect={(positionId, runId) => {
        choosePosition(positionId);
        setInspectedRunId(runId ?? undefined);
        setHistoryRevision((value) => value + 1);
        requestAnimationFrame(() => {
          const target = document.querySelector(runId ? "#positional-run-history" : ".position-stage");
          if (target instanceof HTMLElement) target.focus({ preventScroll: true });
          target?.scrollIntoView({ block: "start" });
        });
      }} />

      <div className="positional-workspace">
        <PositionLibrary positions={positions} selectedId={selectedPositionId} loading={loading} error={error} running={running} onSelect={choosePosition} onRetry={retryPositions} />

        <section className="position-stage" aria-label="Position and test controls" tabIndex={-1}>
          {!selectedPosition || !boardPosition ? (
            <div className="position-stage__empty">
              <Crosshair size={28} strokeWidth={1.7} aria-hidden="true" />
              <h2>{loading ? "Loading positions" : error ? "Position library unavailable" : "Select a position"}</h2>
              <p>{error ? "Retry the library to load a position." : "Choose a matching position to inspect the board and run a single turn."}</p>
            </div>
          ) : (
            <>
              <header className="position-stage__header">
                <div>
                  <h2>{selectedPosition.name}</h2>
                  <p>{selectedPosition.opening ?? tagLabel(selectedPosition.source)} · {selectedPosition.sourceGameId}</p>
                  <PositionTags position={selectedPosition} />
                </div>
                <span>{titleCase(selectedPosition.sideToMove)} to move</span>
              </header>

              <div className="position-stage__content">
                <div className="position-stage__board">
                  <Chessboard position={boardPosition} flipped={false} />
                  <dl className="position-stage__metadata">
                    <div><dt>Source</dt><dd><a href={selectedPosition.sourceUrl} target="_blank" rel="noreferrer">{tagLabel(selectedPosition.source)}</a></dd></div>
                    <div><dt>Dataset</dt><dd>{selectedPosition.datasetVersion}</dd></div>
                    <div><dt>Last move</dt><dd>{selectedPosition.position.san} · ply {selectedPosition.moveCount}</dd></div>
                  </dl>
                  <div className="position-stage__classifiers">
                    <p>{selectedPosition.puzzleRating !== null ? `Puzzle rating ${selectedPosition.puzzleRating}` : "Quiet position · difficulty unrated"}</p>
                    {selectedPosition.themes.length > 0 ? <div className="position-tags" aria-label="Puzzle themes">{selectedPosition.themes.map((theme) => <span className="position-tag" key={theme}>{tagLabel(theme)}</span>)}</div> : null}
                    <details className="position-record"><summary>Position details</summary><dl><div><dt>Position ID</dt><dd>{selectedPosition.id}</dd></div><div><dt>FEN</dt><dd>{selectedPosition.position.fen}</dd></div></dl></details>
                  </div>
                  {runResult ? (
                    <p className="position-stage__board-note">
                      Proposed move: <strong>{runResult.move.san}</strong>. The highlighted squares mark its path on the saved position.
                    </p>
                  ) : null}
                </div>

                <aside className="position-inspector" aria-label="Run a positional test">
                  <fieldset className="agent-picker" disabled={running}>
                    <legend>Choose a harness</legend>
                    <p>Each run proposes one move from this position.</p>
                    {harnessLoading ? (
                      <div className="agent-picker__state" aria-live="polite">Loading harness choices…</div>
                    ) : harnessError ? (
                      <div className="agent-picker__state agent-picker__state--error" role="alert">
                        <span><strong>Harness choices unavailable.</strong> {harnessError}</span>
                        <button type="button" onClick={() => void retryHarnesses()}>
                          <RotateCcw size={14} aria-hidden="true" /> Retry
                        </button>
                      </div>
                    ) : missingHarnesses.length > 0 ? (
                      <div className="agent-picker__state agent-picker__state--error" role="alert">
                        <span>
                          <strong>Expected harness missing.</strong>{" "}
                          The catalog did not return {missingHarnesses.map((harness) => harness.name).join(" or ")}.
                        </span>
                        <button type="button" onClick={() => void retryHarnesses()}>
                          <RotateCcw size={14} aria-hidden="true" /> Reload harnesses
                        </button>
                      </div>
                    ) : (
                      <div className="agent-choice-list">
                        {availableHarnesses.map((harness) => {
                          const selected = harness.id === selectedHarnessId;
                          return (
                            <label
                              className={selected ? "agent-choice agent-choice--selected" : "agent-choice"}
                              key={harness.id}
                            >
                              <input
                                type="radio"
                                name="positional-test-harness"
                                value={harness.id}
                                checked={selected}
                                disabled={running}
                                onChange={(event) => chooseHarness(event.target.value)}
                              />
                              <span className="agent-choice__copy">
                                <strong>{harness.name}</strong>
                                <small>{harness.summary}</small>
                                <code>{harness.version}</code>
                              </span>
                              {selected ? <Check size={18} aria-hidden="true" /> : null}
                            </label>
                          );
                        })}
                      </div>
                    )}
                    <CodexTrainingChoice selected={isCodex} disabled={running} worker={codexWorker}
                      onSelect={() => chooseHarness(CODEX_TRAINING_ID)} />
                  </fieldset>

                  <div className="positional-runbar">
                    <div className="positional-runbar__copy" role="status">
                      {running ? (
                        <LoaderCircle className="spin" size={18} aria-hidden="true" />
                      ) : selectedHarness ? (
                        <Check size={18} aria-hidden="true" />
                      ) : (
                        <Crosshair size={18} aria-hidden="true" />
                      )}
                      <span>
                        <strong>
                          {running
                            ? isCodex ? codexJob?.stopping ? "Stopping Codex" : `Codex · pass ${codexJob?.pass_number ?? 1}` : "Running one turn"
                            : runResult
                              ? `Move ${runResult.move.san} proposed`
                              : selectedHarness
                                ? `${selectedHarness.name} selected`
                                : "Select a harness to begin"}
                        </strong>
                        <small>{running ? isCodex ? codexJob?.progress ?? "Starting Codex…" : "Waiting for the model. This can take a few minutes." : queueActive ? "A full queue is active. Single runs are available when it finishes." : isCodex && !codexWorker?.online ? "Connect the Windows worker to run this position." : "Your saved position stays unchanged."}</small>
                      </span>
                    </div>
                    <button
                      className="positional-runbar__button"
                      type="button"
                      disabled={running || queueActive || !selectedHarness || (isCodex ? !codexWorker?.online : !modelReady || harnessLoading || !!harnessError || missingHarnesses.length > 0)}
                      aria-busy={running}
                      onClick={() => void runOnce()}
                    >
                      {running ? (
                        <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Running one turn…</>
                      ) : (
                        <><Play size={15} fill="currentColor" aria-hidden="true" /> {runError ? "Try again" : runResult ? "Run again" : "Run once"}</>
                      )}
                    </button>
                    {isCodex && running && codexRunId ? <button className="codex-stop" type="button" disabled={codexJob?.stopping} onClick={() => void stopCodex()}><Square size={14} aria-hidden="true" />{codexJob?.stopping ? "Stopping…" : "Stop Codex"}</button> : null}
                  </div>

                  {codexConnectionError && isCodex ? <p className="run-failure" role="alert">{codexConnectionError}</p> : null}

                  {runError ? (
                    <div className="positional-run-error" role="alert">
                      <AlertTriangle size={18} aria-hidden="true" />
                      <span>
                        <strong>{runResult ? "Move saved; grading did not complete." : codexJob?.status === "cancelled" ? "Codex run stopped." : "The agent did not return a move."}</strong>
                        <small>{runError}{isCodex ? " Saved passes are available in run history." : " Check the selected model connection, then try again."}</small>
                      </span>
                    </div>
                  ) : null}
                </aside>
              </div>
            </>
          )}
        </section>
      </div>
      <RunHistory key={`${selectedPositionId}:${inspectedRunId ?? ""}`} positionId={selectedPositionId} preferredRunId={inspectedRunId ?? runResult?.runId} revision={historyRevision} running={running || queueActive} />
    </section>
  );
}
