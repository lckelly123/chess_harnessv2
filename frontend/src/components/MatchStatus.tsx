import { CircleStop, Radio } from "lucide-react";
import type { MatchDetail } from "../api/contracts";

function formatDuration(startedAt: string, endedAt: string | null): string {
  const end = endedAt ? new Date(endedAt).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((end - new Date(startedAt).getTime()) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

interface MatchStatusProps {
  match: MatchDetail;
  displayPly: number;
  replaying: boolean;
  currentMove: string;
  canStop: boolean;
  busy: boolean;
  onStop(): void;
}

export function MatchStatus({ match, displayPly, replaying, currentMove, canStop, busy, onStop }: MatchStatusProps) {
  const currentPlayer = displayPly % 2 === 0 ? match.white : match.black;

  return (
    <section className="match-status" aria-label="Match status">
      <div className="status-heading">
        <div className="status-title">
          <div className="status-title-line">
            <h2>{replaying ? "Replay record" : "Live match"}</h2>
            <span className="record-id">{match.id}</span>
          </div>
          <span className="current-notation"><i className="registration-mark" /> Current move <strong>{currentMove}</strong></span>
        </div>
        <div className="status-actions">
          <span className={`status-badge status-badge--${match.status}`}>
            {match.status === "running" ? <Radio size={13} aria-hidden="true" /> : null}
            {match.status}
          </span>
          {canStop ? (
            <button className="status-stop" type="button" onClick={onStop} disabled={busy}>
              <CircleStop size={15} aria-hidden="true" />
              {busy ? "Stopping…" : "Stop active"}
            </button>
          ) : null}
        </div>
      </div>
      <div className="player-register">
        <div className={`player-row ${currentPlayer.color === "white" ? "player-row--to-move" : ""}`}>
          <span className="color-swatch color-swatch--white" aria-label="White" />
          <strong>{match.white.name}</strong>
          <span>{match.white.version}</span>
        </div>
        <div className={`player-row ${currentPlayer.color === "black" ? "player-row--to-move" : ""}`}>
          <span className="color-swatch color-swatch--black" aria-label="Black" />
          <strong>{match.black.name}</strong>
          <span>{match.black.version}</span>
        </div>
      </div>
      <dl className="match-facts">
        <div><dt>Ply</dt><dd>{displayPly} / {match.moveCount}</dd></div>
        <div><dt>Elapsed</dt><dd>{formatDuration(match.startedAt, match.endedAt)}</dd></div>
        <div><dt>Result</dt><dd>{match.result ?? "—"}</dd></div>
      </dl>
    </section>
  );
}
