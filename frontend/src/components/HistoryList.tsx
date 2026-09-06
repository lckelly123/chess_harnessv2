import { ArrowRight, Folder, Search } from "lucide-react";
import type { GameFolder, MatchSummary } from "../api/contracts";

interface HistoryListProps {
  matches: MatchSummary[];
  total: number;
  query: string;
  selectedId: string | null;
  loading: boolean;
  folders: GameFolder[];
  assigningId: string | null;
  assignmentError: { matchId: string; message: string } | null;
  emptyMessage: string;
  onQueryChange(value: string): void;
  onOpen(matchId: string): void;
  onAssignFolder(matchId: string, folderId: string | null): void;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function HistoryList({
  matches,
  total,
  query,
  selectedId,
  loading,
  folders,
  assigningId,
  assignmentError,
  emptyMessage,
  onQueryChange,
  onOpen,
  onAssignFolder,
}: HistoryListProps) {
  return (
    <section className="history-ledger">
      <header className="history-header">
        <div className="section-heading">
          <div>
            <h2>Match records</h2>
            <p>Search by id, player, version, status, or result</p>
          </div>
          <span>{loading ? "Searching…" : `${total} found`}</span>
        </div>
        <label className="search-control">
          <Search size={17} aria-hidden="true" />
          <span className="sr-only">Search match records</span>
          <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search records" />
        </label>
      </header>
      <div className="history-table" role="list">
        {matches.length === 0 ? (
          <div className="empty-state">{emptyMessage}</div>
        ) : (
          matches.map((match) => (
            <div
              className={`history-row ${selectedId === match.id ? "history-row--selected" : ""}`}
              role="listitem"
              key={match.id}
            >
              <button className="history-open" type="button" onClick={() => onOpen(match.id)}>
                <span className="history-id">{match.id}</span>
                <span className="history-players">
                  <strong>{match.white.name} <small>{match.white.version}</small></strong>
                  <span>vs</span>
                  <strong>{match.black.name} <small>{match.black.version}</small></strong>
                </span>
                <span className="history-date">{formatDate(match.startedAt)}</span>
                <span className={`history-result history-result--${match.status}`}>{match.result ?? match.status}</span>
                <ArrowRight size={16} aria-hidden="true" />
              </button>
              <div className="history-folder-cell">
                <label className="history-folder-control">
                  <Folder size={14} aria-hidden="true" />
                  <span className="sr-only">Folder for {match.id}</span>
                  <select
                    value={match.folder?.id ?? ""}
                    disabled={assigningId === match.id}
                    aria-label={`Folder for ${match.id}`}
                    onChange={(event) => onAssignFolder(match.id, event.target.value || null)}
                  >
                    <option value="">Unfiled</option>
                    {folders.map((folder) => (
                      <option key={folder.id} value={folder.id}>{folder.name}</option>
                    ))}
                  </select>
                </label>
                <span
                  className={assignmentError?.matchId === match.id ? "history-folder-message history-folder-message--error" : "history-folder-message"}
                  role={assignmentError?.matchId === match.id ? "alert" : "status"}
                  aria-live="polite"
                >
                  {assigningId === match.id ? "Moving record…" : assignmentError?.matchId === match.id ? assignmentError.message : ""}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
