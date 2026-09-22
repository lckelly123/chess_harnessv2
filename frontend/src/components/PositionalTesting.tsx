import {
  AlertTriangle,
  Check,
  ChevronRight,
  Crosshair,
  FileText,
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
  const [runError, setRunError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<PositionalTestRun | null>(null);

  useEffect(() => {
    let cancelled = false;
    matchApi.listPositionalTestPositions().then((response) => {
      if (cancelled) return;
      setPositions(response.items);
      setSelectedPositionId((current) =>
        response.items.some((position) => position.id === current) ? current : "",
      );
    }).catch((caught: unknown) => {
      if (!cancelled) {
        setError(caught instanceof Error ? caught.message : "Saved positions could not be loaded.");
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
    () => positions.find((position) => position.id === selectedPositionId) ?? null,
    [positions, selectedPositionId],
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
    if (!selectedPosition || !selectedHarness || running) return;
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
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Saved positions could not be loaded.");
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
        <p>Explore a saved position. Choose a harness and see its next move.</p>
      </header>

      <div className="positional-workspace">
        <aside className="position-index" aria-label="Saved positional tests">
          <header className="position-index__header">
            <div>
              <h2>Saved positions</h2>
              <p>Choose a position to test.</p>
            </div>
            <span aria-label={`${positions.length} saved positions`}>{positions.length}</span>
          </header>

          {loading ? (
            <div className="position-index__state" aria-live="polite">Reading saved positions…</div>
          ) : error ? (
            <div className="position-index__state position-index__state--error" role="alert">
              <p>{error}</p>
              <button type="button" onClick={() => void retryPositions()}>
                <RotateCcw size={14} aria-hidden="true" /> Retry
              </button>
            </div>
          ) : positions.length === 0 ? (
            <div className="position-index__state">
              No saved PGNs found. Add one to <code>positional_testing/positions</code>.
            </div>
          ) : (
            <div className="position-list">
              {positions.map((position) => {
                const selected = position.id === selectedPositionId;
                return (
                  <button
                    className={selected ? "position-row position-row--selected" : "position-row"}
                    type="button"
                    key={position.id}
                    aria-pressed={selected}
                    disabled={running}
                    onClick={() => choosePosition(position.id)}
                  >
                    <FileText size={17} aria-hidden="true" />
                    <span className="position-row__copy">
                      <strong>{position.name}</strong>
                      <span>{position.sourceFile}</span>
                      <small>{titleCase(position.sideToMove)} to move · ply {position.moveCount}</small>
                    </span>
                    <ChevronRight size={16} aria-hidden="true" />
                  </button>
                );
              })}
            </div>
          )}
        </aside>

        <section className="position-stage" aria-label="Position and test controls">
          {!selectedPosition || !boardPosition ? (
            <div className="position-stage__empty">
              <Crosshair size={28} strokeWidth={1.7} aria-hidden="true" />
              <h2>Select a saved position</h2>
              <p>Choose a saved position to inspect the board and run a single turn.</p>
            </div>
          ) : (
            <>
              <header className="position-stage__header">
                <div>
                  <h2>{selectedPosition.name}</h2>
                  <p>
                    {selectedPosition.white && selectedPosition.black
                      ? `${selectedPosition.white} vs ${selectedPosition.black}`
                      : selectedPosition.sourceFile}
                  </p>
                </div>
                <span>{titleCase(selectedPosition.sideToMove)} to move</span>
              </header>

              <div className="position-stage__content">
                <div className="position-stage__board">
                  <Chessboard position={boardPosition} flipped={false} />
                  <dl className="position-stage__metadata">
                    <div><dt>Source</dt><dd>{selectedPosition.sourceFile}</dd></div>
                    <div><dt>Ply</dt><dd>{selectedPosition.moveCount}</dd></div>
                  </dl>
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
                        <small>{running ? "Waiting for the model. This can take a few minutes." : "Your saved position stays unchanged."}</small>
                      </span>
                    </div>
                    <button
                      className="positional-runbar__button"
                      type="button"
                      disabled={running || !selectedHarness || harnessLoading || !!harnessError || missingHarnesses.length > 0}
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

              {runResult ? (
                <section className="positional-result" aria-labelledby="positional-result-title">
                  <header className="positional-result__header">
                    <div>
                      <h3 id="positional-result-title">Proposed move</h3>
                      <p>{runResult.harnessName} completed one turn from ply {runResult.ply}.</p>
                    </div>
                    <span><Check size={13} aria-hidden="true" /> Complete</span>
                  </header>

                  <div className="positional-result__move">
                    <strong>{runResult.move.san}</strong>
                    <code>{runResult.move.uci}</code>
                    <dl>
                      <div><dt>Side</dt><dd>{titleCase(runResult.side)}</dd></div>
                      <div><dt>Harness</dt><dd>{runResult.harnessName}</dd></div>
                      <div><dt>Model</dt><dd>{runResult.model}</dd></div>
                      <div><dt>Run</dt><dd>{runResult.runId}</dd></div>
                    </dl>
                  </div>

                  <div className="positional-result__text">
                    <h4>Justification</h4>
                    <p>{runResult.justification}</p>
                  </div>

                  {runResult.defenseReport || runResult.attackReport ? (
                    <div className="positional-result__reports">
                      {runResult.defenseReport ? (
                        <div>
                          <h4>Defense report</h4>
                          <p>{runResult.defenseReport}</p>
                        </div>
                      ) : null}
                      {runResult.attackReport ? (
                        <div>
                          <h4>Attack report</h4>
                          <p>{runResult.attackReport}</p>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ) : null}
            </>
          )}
        </section>
      </div>
    </section>
  );
}
