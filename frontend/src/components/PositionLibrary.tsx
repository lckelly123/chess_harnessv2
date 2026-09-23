import { ChevronDown, ChevronLeft, ChevronRight, RotateCcw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { PositionalTestPosition } from "../api/contracts";
import { EMPTY_POSITION_FILTERS, filterPositions, tagLabel } from "./positionFilters";
import type { PositionFilters } from "./positionFilters";

const PAGE_SIZE = 12;

export function PositionTags({ position }: { position: PositionalTestPosition }) {
  return <span className="position-tags">
    <span className={`position-tag position-tag--${position.split}`}>{tagLabel(position.split)}</span>
    <span className="position-tag">{tagLabel(position.phase)}</span>
    <span className="position-tag">{tagLabel(position.positionType)}</span>
  </span>;
}

interface PositionLibraryProps {
  positions: PositionalTestPosition[];
  selectedId: string;
  loading: boolean;
  error: string | null;
  running: boolean;
  onSelect: (id: string) => void;
  onRetry: () => Promise<PositionalTestPosition[] | null>;
}

export function PositionLibrary({ positions, selectedId, loading, error, running, onSelect, onRetry }: PositionLibraryProps) {
  const [filters, setFilters] = useState<PositionFilters>(EMPTY_POSITION_FILTERS);
  const [page, setPage] = useState(0);
  const filtered = useMemo(() => filterPositions(positions, filters), [positions, filters]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const shown = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const versions = [...new Set(positions.map((position) => position.datasetVersion))].sort();
  const themes = [...new Set(positions.flatMap((position) => position.themes))].sort();
  const hasFilters = Object.values(filters).some(Boolean);
  const moreCount = [filters.datasetVersion, filters.theme, filters.source, filters.rating].filter(Boolean).length;

  const changeFilters = (next: PositionFilters) => {
    setFilters(next);
    setPage(0);
    onSelect(filterPositions(positions, next)[0]?.id ?? "");
  };
  const selectFilter = (field: keyof PositionFilters, label: string, options: [string, string][]) => (
    <label className="field-control">
      <span>{label}</span>
      <select aria-label={label} value={filters[field]} onChange={(event) => changeFilters({ ...filters, [field]: event.target.value })}>
        {options.map(([value, text]) => <option value={value} key={value}>{text}</option>)}
      </select>
    </label>
  );
  const changePage = (next: number) => {
    setPage(next);
    onSelect(filtered[next * PAGE_SIZE]?.id ?? "");
  };
  const refresh = async () => {
    const updated = await onRetry();
    if (!updated) return;
    const matches = filterPositions(updated, filters);
    if (!matches.some((position) => position.id === selectedId)) {
      setPage(0);
      onSelect(matches[0]?.id ?? "");
    }
  };

  return <aside className="position-index" aria-label="Position library">
    <header className="position-index__header">
      <div><h2>Position library</h2><p role="status">{loading ? "Loading positions…" : `${filtered.length} of ${positions.length} positions`}</p></div>
      <button className="icon-button" type="button" aria-label="Refresh position library" disabled={loading || running} onClick={() => void refresh()}><RotateCcw size={16} aria-hidden="true" /></button>
    </header>

    <fieldset className="position-filters" disabled={running || loading || Boolean(error)}>
      <legend className="sr-only">Filter positions</legend>
      <label className="position-search">
        <Search size={16} aria-hidden="true" />
        <span className="sr-only">Search positions</span>
        <input type="search" placeholder="Opening, theme or ID…" value={filters.query} onChange={(event) => changeFilters({ ...filters, query: event.target.value })} />
      </label>
      <div className="position-filters__grid">
        {selectFilter("split", "Set", [["", "All sets"], ["train", "Training"], ["test", "Test"]])}
        {selectFilter("phase", "Phase", [["", "All phases"], ["opening", "Opening"], ["middlegame", "Middlegame"], ["endgame", "Endgame"]])}
        {selectFilter("positionType", "Position type", [["", "All types"], ["quiet", "Quiet"], ["tactical", "Tactical"]])}
        {selectFilter("sideToMove", "Side to move", [["", "Both sides"], ["white", "White"], ["black", "Black"]])}
      </div>
      <details className="position-filters__more">
        <summary>More filters{moreCount > 0 ? ` (${moreCount})` : ""}<ChevronDown size={15} aria-hidden="true" /></summary>
        <div className="position-filters__grid">
          {selectFilter("datasetVersion", "Dataset", [["", "All versions"], ...versions.map((version): [string, string] => [version, version])])}
          {selectFilter("source", "Source", [["", "All sources"], ["lichess_game", "Lichess game"], ["lichess_puzzle", "Lichess puzzle"]])}
          {selectFilter("theme", "Puzzle theme", [["", "All themes"], ...themes.map((theme): [string, string] => [theme, tagLabel(theme)])])}
          {selectFilter("rating", "Puzzle rating", [["", "Any rating"], ["under1400", "Below 1400"], ["1400to1799", "1400–1799"], ["1800plus", "1800 and above"], ["unrated", "Unrated"]])}
        </div>
      </details>
      {hasFilters ? <button type="button" className="position-filters__clear" onClick={() => changeFilters(EMPTY_POSITION_FILTERS)}>Clear filters</button> : null}
    </fieldset>

    {loading ? <div className="position-index__state" aria-live="polite">Loading the library…</div>
      : error ? <div className="position-index__state position-index__state--error" role="alert"><p>{error}</p><button type="button" onClick={() => void refresh()} disabled={running}><RotateCcw size={14} aria-hidden="true" /> Retry</button></div>
      : positions.length === 0 ? <div className="position-index__state">The position library is empty. Import a dataset, then refresh.</div>
      : filtered.length === 0 ? <div className="position-index__state"><p>No positions match these filters.</p><button type="button" disabled={running} onClick={() => changeFilters(EMPTY_POSITION_FILTERS)}>Clear filters</button></div>
      : <>
        <div className="position-list" aria-label="Matching positions">
          {shown.map((position) => <button className={`position-row${selectedId === position.id ? " position-row--selected" : ""}`} type="button" key={position.id} aria-pressed={selectedId === position.id} disabled={running} onClick={() => onSelect(position.id)}>
            <span className="position-row__copy">
              <strong>{position.name}</strong>
              <PositionTags position={position} />
              <small>{tagLabel(position.sideToMove)} to move · {position.datasetVersion}{position.puzzleRating !== null ? ` · rated ${position.puzzleRating}` : ""}</small>
              <span className="position-row__id">{position.sourceGameId}</span>
            </span>
            <ChevronRight size={16} aria-hidden="true" />
          </button>)}
        </div>
        <nav className="position-pagination" aria-label="Position pages">
          <button className="icon-button" type="button" aria-label="Previous positions" disabled={running || currentPage === 0} onClick={() => changePage(currentPage - 1)}><ChevronLeft size={17} aria-hidden="true" /></button>
          <span>{currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}</span>
          <button className="icon-button" type="button" aria-label="Next positions" disabled={running || currentPage + 1 >= pageCount} onClick={() => changePage(currentPage + 1)}><ChevronRight size={17} aria-hidden="true" /></button>
        </nav>
      </>}
  </aside>;
}
