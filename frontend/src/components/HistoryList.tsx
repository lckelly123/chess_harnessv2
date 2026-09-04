import { ArrowRight, Search } from "lucide-react";
import type { MatchSummary } from "../api/contracts";

interface HistoryListProps {
  matches: MatchSummary[];
  total: number;
  query: string;
  selectedId: string | null;
  loading: boolean;
  onQueryChange(value: string): void;
  onOpen(matchId: string): void;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function HistoryList({ matches, total, query, selectedId, loading, onQueryChange, onOpen }: HistoryListProps) {
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
          <div className="empty-state">No match records fit that search. Try a player or status.</div>
        ) : (
          matches.map((match) => (
            <button
              className={`history-row ${selectedId === match.id ? "history-row--selected" : ""}`}
              type="button"
              role="listitem"
              key={match.id}
              onClick={() => onOpen(match.id)}
            >
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
          ))
        )}
      </div>
    </section>
  );
}

