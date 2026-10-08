import { ArrowRight, Folder, Search, Trash2 } from "lucide-react";
import { useId, useMemo, useRef, useState } from "react";
import type { GameFolder, MatchSummary } from "../api/contracts";
import { DeleteRunDialog } from "./DeleteRunDialog";

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
  onDelete(matchId: string): Promise<void>;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
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
  onDelete,
}: HistoryListProps) {
  const orderId = useId();
  const sectionRef = useRef<HTMLElement>(null);
  const [deleteTarget, setDeleteTarget] = useState<MatchSummary | null>(null);
  const [order, setOrder] = useState("newest");
  const orderedMatches = useMemo(() => [...matches].sort((a, b) => {
    const difference = new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime() || b.id.localeCompare(a.id);
    return order === "newest" ? difference : -difference;
  }), [matches, order]);
  return (
    <section className="history-ledger" ref={sectionRef} tabIndex={-1} aria-label="Recorded matches">
      {deleteTarget ? <DeleteRunDialog kind="match" recordId={deleteTarget.id} label={`${deleteTarget.white.name} vs ${deleteTarget.black.name}`} fallbackFocus={sectionRef} onDelete={() => onDelete(deleteTarget.id)} onCancel={() => setDeleteTarget(null)} /> : null}
      <header className="history-header">
        <div className="section-heading">
          <div>
            <h2>Recorded matches</h2>
            <p>Search by player, version, result, or ID.</p>
          </div>
          <span>{loading ? "Searching…" : `${total} found`}</span>
        </div>
        <div className="history-controls"><label className="search-control">
          <Search size={17} aria-hidden="true" />
          <span className="sr-only">Search match records</span>
          <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search records" />
        </label>
        <label className="field-control" htmlFor={orderId}><span>Order</span><select id={orderId} value={order} onChange={(event) => setOrder(event.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label></div>
      </header>
      <div className="history-scroll" role="region" aria-label="Browse recorded matches" tabIndex={0}><div className="history-table" role="list">
        {matches.length === 0 ? (
          <div className="empty-state">{emptyMessage}</div>
        ) : (
          orderedMatches.map((match) => (
            <div
              className={`history-row ${selectedId === match.id ? "history-row--selected" : ""}`}
              role="listitem"
              key={match.id}
            >
              <button className="history-open" type="button" aria-current={selectedId === match.id ? "true" : undefined} onClick={() => onOpen(match.id)}>
                <span className="history-record">
                <span className="history-players">
                  <strong>{match.white.name}</strong>
                  <span>vs</span>
                  <strong>{match.black.name}</strong>
                </span>
                <span className="history-id">{match.id}</span>
                <time className="history-timestamp" dateTime={match.startedAt}>{formatDate(match.startedAt)}</time>
                </span>
                <span className={`history-result history-result--${match.status}`}>{match.result === "aborted" ? "stopped" : match.result ?? match.status}</span>
                <ArrowRight size={16} aria-hidden="true" />
              </button>
              <details className="history-versions"><summary>Harness versions</summary><span>White · {match.white.version}</span><span>Black · {match.black.version}</span></details>
              <div className="history-row-actions"><div className="history-folder-cell">
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
              <button className="icon-button icon-button--delete" type="button" aria-label={`Delete match ${match.id}`} title="Delete match" onClick={() => setDeleteTarget(match)}><Trash2 size={16} aria-hidden="true" /></button>
              </div>
            </div>
          ))
        )}
      </div>
      </div>
    </section>
  );
}
