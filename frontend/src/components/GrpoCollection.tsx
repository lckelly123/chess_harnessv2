import { Check, LoaderCircle, Play, RotateCcw, Square } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ModelSelection } from "../api/contracts";
import { grpoActive, grpoApi, type GrpoGroup, type GrpoStatus } from "../api/grpo";

interface GrpoCollectionProps {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  positionId: string;
  harnessId: string;
  modelSelection: ModelSelection;
  modelReady: boolean;
  running: boolean;
  queueActive: boolean;
  onRunningChange: (running: boolean) => void;
  onAttach: (group: GrpoGroup) => void;
  onFinished: () => void;
}

export function GrpoCollection({ enabled, onEnabledChange, positionId, harnessId, modelSelection, modelReady, running, queueActive, onRunningChange, onAttach, onFinished }: GrpoCollectionProps) {
  const fieldId = useId();
  const [name, setName] = useState("");
  const [group, setGroup] = useState<GrpoGroup | null>(null);
  const [status, setStatus] = useState<GrpoStatus | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopPending, setStopPending] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const groupRef = useRef<GrpoGroup | null>(null);
  const mutationVersion = useRef(0);
  const commandPending = useRef(false);
  const attached = useRef<string | null>(null);
  const active = grpoActive(group);
  const busy = active || starting;
  const eligible = modelSelection.modelId === "unsloth" && harnessId === "agent-player-2-langgraph-v1";
  const trimmedName = name.trim();
  const nameValid = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(trimmedName) && !/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(trimmedName) && !trimmedName.endsWith(".");

  const applyGroup = useCallback((next: GrpoGroup) => {
    const wasActive = grpoActive(groupRef.current);
    groupRef.current = next;
    setGroup(next);
    if (grpoActive(next)) {
      if (attached.current !== next.name) {
        attached.current = next.name;
        setName(next.name);
        onEnabledChange(true);
        onAttach(next);
      }
      onRunningChange(true);
    } else if (wasActive || attached.current === next.name) {
      attached.current = null;
      setStopPending(false);
      onRunningChange(false);
      onFinished();
    }
  }, [onAttach, onEnabledChange, onFinished, onRunningChange]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const version = mutationVersion.current;
      try {
        const nextStatus = await grpoApi.status();
        if (cancelled || version !== mutationVersion.current) return;
        setStatus(nextStatus);
        const current = groupRef.current;
        const nextGroup = nextStatus.activeRun ?? (grpoActive(current) && current ? await grpoApi.group(current.name) : null);
        if (cancelled || version !== mutationVersion.current) return;
        setConnectionError(null);
        if (nextGroup) applyGroup(nextGroup);
      } catch (caught) {
        if (!cancelled && version === mutationVersion.current) {
          setConnectionError(caught instanceof Error ? caught.message : "Could not check the collection status. Reconnecting…");
        }
      } finally {
        if (!cancelled) timer = setTimeout(() => void poll(), 2000);
      }
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [applyGroup, refresh]);

  const start = async () => {
    if (commandPending.current || busy || running || queueActive || !eligible || !modelReady || !modelSelection.modelName || !nameValid || !status?.workerOnline || connectionError) return;
    commandPending.current = true;
    mutationVersion.current++;
    setStarting(true);
    setActionError(null);
    onRunningChange(true);
    try {
      const next = await grpoApi.start({ name: trimmedName, positionId, harnessId, modelSelection });
      applyGroup(next);
      if (!grpoActive(next)) onRunningChange(false);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "The collection could not be started. Try again.");
      onRunningChange(false);
    } finally {
      commandPending.current = false;
      setStarting(false);
      mutationVersion.current++;
      setRefresh((value) => value + 1);
    }
  };

  const stop = async () => {
    const current = groupRef.current;
    if (!current || !grpoActive(current) || commandPending.current || stopPending || current.stopping) return;
    commandPending.current = true;
    mutationVersion.current++;
    setStopPending(true);
    setActionError(null);
    try {
      applyGroup(await grpoApi.stop(current.name));
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "The collection could not be stopped. Try again.");
      setStopPending(false);
    } finally {
      commandPending.current = false;
      mutationVersion.current++;
      setRefresh((value) => value + 1);
    }
  };

  const blockingReason = !eligible ? "Choose Unsloth and the chess_harness to save GRPO trajectories."
    : queueActive ? "Wait for the active queue to finish before starting a collection."
      : !modelReady || !modelSelection.modelName ? "Select a loaded Unsloth adapter in Model settings."
        : !status ? "Checking the GRPO capture worker…"
          : !status.workerOnline ? status.workerMessage ?? "Start the GRPO capture worker, then retry."
            : null;
  const failed = group?.trajectories.filter((trajectory) => trajectory.status === "failed" || trajectory.status === "interrupted").length ?? 0;
  const shown = enabled || busy;
  const stopping = stopPending || !!group?.stopping;

  return <section className="grpo-collection" aria-label="GRPO collection">
    <label className="grpo-collection__toggle">
      <input type="checkbox" checked={shown} disabled={running || busy || queueActive || (!eligible && !shown)} onChange={(event) => { onEnabledChange(event.target.checked); setActionError(null); }} aria-describedby={`${fieldId}-help`} />
      <span><strong>Save for GRPO</strong><small id={`${fieldId}-help`}>{!eligible && !busy ? "Choose Unsloth and chess_harness to collect 10 trajectories." : "Collect 10 trajectories from this position, one at a time."}</small></span>
    </label>
    {shown ? <div className="grpo-collection__body">
      <label className="field-control" htmlFor={fieldId}>
        <span>Run name</span>
        <input id={fieldId} value={name} required maxLength={80} disabled={busy || running || queueActive} placeholder="e.g. endgame-v2.3" autoComplete="off" spellCheck={false}
          aria-invalid={!!trimmedName && !nameValid} aria-describedby={`${fieldId}-destination${trimmedName && !nameValid ? ` ${fieldId}-invalid` : ""}`}
          onChange={(event) => { setName(event.target.value); setActionError(null); }} />
      </label>
      <p id={`${fieldId}-destination`} className="grpo-collection__destination">Save to <code>models/training_data/RL_testing/{trimmedName || "[run name]"}/</code></p>
      {trimmedName && !nameValid ? <p id={`${fieldId}-invalid`} className="run-failure">Use 1–80 letters, numbers, dots, hyphens or underscores. Start with a letter or number; do not end with a dot or use a reserved folder name.</p> : null}
      {!busy && blockingReason ? <p className="grpo-collection__help">{blockingReason}</p> : null}
      {connectionError ? <div className="grpo-collection__connection" role="alert"><span>{active ? "Connection interrupted. The collection may still be running. " : "Could not check GRPO readiness. "}{connectionError}</span><button type="button" className="model-settings__refresh" onClick={() => setRefresh((value) => value + 1)}><RotateCcw size={14} aria-hidden="true" /> Retry</button></div> : null}
      {group ? <div className="grpo-collection__progress" role="status">
        <strong>{active ? stopping ? "Stopping collection" : group.status === "preparing" ? "Preparing collection" : `Trajectory ${group.currentTrajectory ?? 1}/${group.totalTrajectories} · Model call ${group.currentCall}` : group.status === "completed" ? "Collection complete" : group.status === "stopped" ? "Collection stopped" : group.status === "interrupted" ? "Collection interrupted" : "Collection failed"}</strong>
        <span>{group.completedTrajectories}/{group.totalTrajectories} attempts finished{failed > 0 ? ` · ${failed} failed` : ""}</span>
        <small>{active ? stopping ? "Saving the current partial response. Captured files will be kept." : "The manifest and trajectory files update as calls finish." : "Captured files have been kept."}</small>
        {!active ? <code>{group.outputDirectory}</code> : null}
      </div> : null}
      {group?.error ? <p className="run-failure" role="alert">{group.error}</p> : null}
      {actionError ? <p className="run-failure" role="alert">{actionError}</p> : null}
      <button type="button" className="positional-runbar__button" disabled={busy || running || !!blockingReason || !nameValid || !!connectionError} aria-busy={busy} onClick={() => void start()}>
        {busy ? <><LoaderCircle className="spin" size={16} aria-hidden="true" />{stopping ? "Stopping…" : starting || group?.status === "preparing" ? "Preparing collection…" : "Collecting trajectories…"}</> : <><Play size={15} fill="currentColor" aria-hidden="true" />Run 10 trajectories</>}
      </button>
      {active ? <button type="button" className="codex-stop" disabled={stopping} onClick={() => void stop()}><Square size={14} aria-hidden="true" />{stopping ? "Stopping…" : actionError ? "Retry stop collection" : "Stop collection"}</button> : null}
      {!busy && !blockingReason && !connectionError ? <p className="grpo-collection__help"><Check size={14} aria-hidden="true" />Capture worker ready. Failed attempts count toward the ten trajectories.</p> : null}
    </div> : null}
  </section>;
}
