import { Check } from "lucide-react";
import { CODEX_TRAINING_ID, type CodexWorkerStatus } from "../api/codex";

export function CodexTrainingChoice({ selected, disabled, worker, onSelect }: {
  selected: boolean;
  disabled: boolean;
  worker: CodexWorkerStatus | null;
  onSelect: () => void;
}) {
  return (
    <div className="codex-training-choice">
      <label className={selected ? "agent-choice agent-choice--selected" : "agent-choice"}>
        <input type="radio" name="positional-test-harness" value={CODEX_TRAINING_ID}
          checked={selected} disabled={disabled} onChange={onSelect} />
        <span className="agent-choice__copy">
          <strong>Codex (training)</strong>
          <small>Create training examples with chess_harness.</small>
          <small>{worker?.online ? `${worker.model} · ${worker.reasoning_effort} reasoning` : "Windows worker offline"}</small>
        </span>
        {selected ? <Check size={18} aria-hidden="true" /> : null}
      </label>
      {selected && !worker?.online ? (
        <p className="codex-training-help">Start the Windows worker from the project folder:<br />
          <code>.\scripts\start-codex-worker.ps1</code><br />Availability updates automatically.</p>
      ) : selected ? (
        <p className="codex-training-help">Uses your Codex sign-in. Explanations, working notes, and tool calls are saved with each pass.</p>
      ) : null}
    </div>
  );
}
