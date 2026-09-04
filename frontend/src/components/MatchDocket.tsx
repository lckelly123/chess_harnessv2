import { Play } from "lucide-react";
import type { FormEvent } from "react";
import type { HarnessVersion } from "../api/contracts";

interface MatchDocketProps {
  harnesses: HarnessVersion[];
  whiteId: string;
  blackId: string;
  busy: boolean;
  onWhiteChange(value: string): void;
  onBlackChange(value: string): void;
  onStart(): void;
}

export function MatchDocket({
  harnesses,
  whiteId,
  blackId,
  busy,
  onWhiteChange,
  onBlackChange,
  onStart,
}: MatchDocketProps) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onStart();
  };
  return (
    <form className="match-docket" onSubmit={submit}>
      <div className="docket-title">
        <span className="docket-number">NEW MATCH</span>
        <p>Choose two versioned harnesses. The mock service supplies every position and trace.</p>
      </div>
      <label className="field-control">
        <span>White harness</span>
        <select value={whiteId} onChange={(event) => onWhiteChange(event.target.value)} disabled={busy}>
          {harnesses.map((harness) => (
            <option key={harness.id} value={harness.id}>
              {harness.name} · {harness.version}
            </option>
          ))}
        </select>
      </label>
      <span className="versus-mark" aria-hidden="true">vs</span>
      <label className="field-control">
        <span>Black harness</span>
        <select value={blackId} onChange={(event) => onBlackChange(event.target.value)} disabled={busy}>
          {harnesses.map((harness) => (
            <option key={harness.id} value={harness.id}>
              {harness.name} · {harness.version}
            </option>
          ))}
        </select>
      </label>
      <div className="docket-actions">
        <button className="button button--primary" type="submit" disabled={busy || !whiteId || !blackId}>
          <Play size={16} strokeWidth={2} aria-hidden="true" />
          {busy ? "Starting…" : "Start mock match"}
        </button>
      </div>
    </form>
  );
}
