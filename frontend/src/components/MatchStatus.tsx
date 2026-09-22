import { CircleStop, Folder, Radio } from "lucide-react";
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
  const replayPlayer = displayPly % 2 === 0 ? match.white : match.black;
  const currentPlayer = replaying
    ? replayPlayer
    : match.currentPlayer
      ? match.currentPlayer === "white" ? match.white : match.black
      : null;

  return (
    <section className="match-status" aria-label="Match status">
      <div className="status-heading">
        <div className="status-title-line">
          <h2>{replaying ? "Match replay" : "Live match"}</h2>
          <span className="match-folder-label"><Folder size={13} aria-hidden="true" />{match.folder?.name ?? "Unfiled"}</span>
        </div>
        <div className="status-actions">
          <span className={`status-badge status-badge--${match.status}`}>
            {match.status === "running" ? <Radio size={12} aria-hidden="true" /> : null}
            {match.status}
          </span>
          {canStop ? <button className="status-stop" type="button" onClick={onStop} disabled={busy}><CircleStop size={15} aria-hidden="true" />{busy ? "Stopping…" : "Stop"}</button> : null}
        </div>
      </div>
      <div className="player-register">
        {[match.white, match.black].map((player) => (
          <div className={`player-row ${currentPlayer?.color === player.color ? "player-row--to-move" : ""}`} key={player.color}>
            <span className={`color-swatch color-swatch--${player.color}`} aria-hidden="true" />
            <div><span className="player-side">{player.color}{currentPlayer?.color === player.color ? " · to move" : ""}</span><strong>{player.name}</strong></div>
          </div>
        ))}
      </div>
      <div className="position-status">
        <span className="current-notation">{displayPly === 0 ? "Position" : "Move"}<strong>{currentMove}</strong></span>
        <dl className="match-facts"><div><dt>Ply</dt><dd>{displayPly} / {match.moveCount}</dd></div><div><dt>Elapsed</dt><dd>{formatDuration(match.startedAt, match.endedAt)}</dd></div>{match.status === "running" && match.currentPhase ? <div><dt>Phase</dt><dd>{match.currentPhase}</dd></div> : null}</dl>
      </div>
    </section>
  );
}
