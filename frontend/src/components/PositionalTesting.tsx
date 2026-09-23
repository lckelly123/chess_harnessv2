import {
  AlertTriangle,
  Check,
  Crosshair,
  LoaderCircle,
  Play,
  RotateCcw,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { matchApi } from "../api/client";
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
  { id: "agent-player-1-langgraph-v1", name: "Agent Player 1" },
  { id: "agent-player-2-langgraph-v1", name: "Agent Player 2" },
  { id: "agent-player-3-langgraph-v1", name: "Agent Player 3" },
];

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

interface PositionalTestingProps {
  modelSelection: ModelSelection;
  running: boolean;
  onRunningChange: (running: boolean) => void;
}

export function PositionalTesting({ modelSelection, running, onRunningChange }: PositionalTestingProps) {
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

  const selectedHarness = availableHarnesses.find(
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
    if (!selectedPosition || !selectedHarness || running || queueActive) return;
    onRunningChange(true);
    setRunError(null);
    setRunResult(null);
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
      if (!response.some((harness) => harness.id === selectedHarnessId)) {
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

      <PositionQueue positions={positions} harnesses={availableHarnesses} modelSelection={modelSelection} singleRunning={running} onActiveChange={setQueueActive} onInspect={(positionId, runId) => {
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
                            ? "Running one turn"
                            : runResult
                              ? `Move ${runResult.move.san} proposed`
                              : selectedHarness
                                ? `${selectedHarness.name} selected`
                                : "Select a harness to begin"}
                        </strong>
                        <small>{running ? "Waiting for the model. This can take a few minutes." : queueActive ? "A full queue is active. Single runs are available when it finishes." : "Your saved position stays unchanged."}</small>
                      </span>
                    </div>
                    <button
                      className="positional-runbar__button"
                      type="button"
                      disabled={running || queueActive || !selectedHarness || harnessLoading || !!harnessError || missingHarnesses.length > 0}
                      aria-busy={running}
                      onClick={() => void runOnce()}
                    >
                      {running ? (
                        <><LoaderCircle className="spin" size={16} aria-hidden="true" /> Running one turn…</>
                      ) : (
                        <><Play size={15} fill="currentColor" aria-hidden="true" /> {runError ? "Try again" : runResult ? "Run again" : "Run once"}</>
                      )}
                    </button>
                  </div>

                  {runError ? (
                    <div className="positional-run-error" role="alert">
                      <AlertTriangle size={18} aria-hidden="true" />
                      <span>
                        <strong>The agent did not return a move.</strong>
                        <small>{runError} Check the selected model connection, then try again.</small>
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
