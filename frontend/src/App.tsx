import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowUpRight, ChevronDown, FlaskConical, LayoutGrid, Library, Plus, RotateCcw, Server, X } from "lucide-react";
import { matchApi } from "./api/client";
import type { GameFolder, HarnessVersion, MatchDetail, MatchSummary, ModelSelection } from "./api/contracts";
import { Chessboard } from "./components/Chessboard";
import { FolderRail } from "./components/FolderRail";
import { HistoryList } from "./components/HistoryList";
import { MatchDocket } from "./components/MatchDocket";
import { MatchStatus } from "./components/MatchStatus";
import { ModelSelector } from "./components/ModelSelector";
import { PositionalTesting } from "./components/PositionalTesting";
import { ReplayControls } from "./components/ReplayControls";
import { TracePanel } from "./components/TracePanel";

type DeskMode = "live" | "replay";
type FolderFilter = "all" | "unfiled" | string;
type WorkspaceSection = "matches" | "records" | "positional-testing";

export default function App() {
  const [harnesses, setHarnesses] = useState<HarnessVersion[]>([]);
  const [folders, setFolders] = useState<GameFolder[]>([]);
  const [allMatchCount, setAllMatchCount] = useState(0);
  const [unfiledCount, setUnfiledCount] = useState(0);
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [totalMatches, setTotalMatches] = useState(0);
  const [selectedMatch, setSelectedMatch] = useState<MatchDetail | null>(null);
  const [activeMatchId, setActiveMatchId] = useState<string | null>(null);
  const [whiteId, setWhiteId] = useState("");
  const [blackId, setBlackId] = useState("");
  const [startFolderId, setStartFolderId] = useState("");
  const [folderFilter, setFolderFilter] = useState<FolderFilter>("all");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<DeskMode>("live");
  const [workspaceSection, setWorkspaceSection] = useState<WorkspaceSection>("matches");
  const [setupOpen, setSetupOpen] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [modelSelection, setModelSelection] = useState<ModelSelection>({
    modelId: "qwen",
    reasoningEffort: "medium",
  });
  const [positionalRunning, setPositionalRunning] = useState(false);
  const [displayPly, setDisplayPly] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [folderBusy, setFolderBusy] = useState(false);
  const [folderError, setFolderError] = useState<string | null>(null);
  const [assigningMatchId, setAssigningMatchId] = useState<string | null>(null);
  const [assignmentError, setAssignmentError] = useState<{ matchId: string; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshMatches = useCallback(async (search = "", folder: FolderFilter = "all") => {
    const apiFolder = folder === "all" ? undefined : folder === "unfiled" ? null : folder;
    const response = await matchApi.listMatches(search, apiFolder);
    setMatches(response.items);
    setTotalMatches(response.total);
    return response.items;
  }, []);

  const refreshFolders = useCallback(async () => {
    const response = await matchApi.listFolders();
    setFolders(response.items);
    setAllMatchCount(response.totalMatches);
    setUnfiledCount(response.unfiledCount);
    return response;
  }, []);

  const openMatch = useCallback(async (matchId: string, nextMode: DeskMode) => {
    setError(null);
    const detail = await matchApi.getMatch(matchId);
    setSelectedMatch(detail);
    setMode(nextMode);
    setDisplayPly(detail.moveCount);
    setPlaying(false);
    if (detail.status === "running") setActiveMatchId(detail.id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [availableHarnesses, , availableMatches] = await Promise.all([
          matchApi.listHarnesses(),
          refreshFolders(),
          refreshMatches("", "all"),
        ]);
        if (cancelled) return;
        setHarnesses(availableHarnesses);
        setWhiteId(availableHarnesses[0]?.id ?? "");
        setBlackId(availableHarnesses[1]?.id ?? availableHarnesses[0]?.id ?? "");
        const initial = availableMatches.find((match) => match.status === "running") ?? availableMatches[0];
        if (initial) await openMatch(initial.id, initial.status === "running" ? "live" : "replay");
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load the match desk.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [openMatch, refreshFolders, refreshMatches]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      refreshMatches(query, folderFilter).catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : "Could not search match records.");
      });
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [folderFilter, query, refreshMatches]);

  useEffect(() => {
    if (!activeMatchId || mode !== "live" || selectedMatch?.status !== "running") return;
    const interval = window.setInterval(() => {
      matchApi.getMatch(activeMatchId).then((detail) => {
        setSelectedMatch(detail);
        setDisplayPly(detail.moveCount);
        if (detail.status !== "running" && detail.status !== "queued") {
          setActiveMatchId((current) => current === detail.id ? null : current);
          void refreshMatches(query, folderFilter);
        }
      }).catch(() => setError("Live refresh failed. The last backend snapshot is still shown."));
    }, 3000);
    return () => window.clearInterval(interval);
  }, [activeMatchId, folderFilter, mode, query, refreshMatches, selectedMatch?.status]);

  useEffect(() => {
    if (!playing || !selectedMatch) return;
    if (displayPly >= selectedMatch.moveCount) return;
    const timeout = window.setTimeout(() => {
      const nextPly = Math.min(displayPly + 1, selectedMatch.moveCount);
      setDisplayPly(nextPly);
      if (nextPly === selectedMatch.moveCount) setPlaying(false);
    }, 900);
    return () => window.clearTimeout(timeout);
  }, [displayPly, playing, selectedMatch]);

  const position = useMemo(() => {
    if (!selectedMatch) return null;
    return selectedMatch.positions.find((item) => item.ply === displayPly) ?? selectedMatch.positions.at(-1) ?? null;
  }, [displayPly, selectedMatch]);

  const navigateWorkspace = (section: WorkspaceSection) => {
    setWorkspaceSection(section);
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: "instant" });
      headingRef.current?.focus({ preventScroll: true });
    });
  };

  const startMatch = async () => {
    setBusy(true);
    setError(null);
    try {
      const detail = await matchApi.startMatch({
        whiteHarnessId: whiteId,
        blackHarnessId: blackId,
        folderId: startFolderId || null,
        modelSelection,
      });
      setActiveMatchId(detail.id);
      setSelectedMatch(detail);
      setMode("live");
      setDisplayPly(detail.moveCount);
      setSetupOpen(false);
      await Promise.all([
        refreshMatches(query, folderFilter),
        refreshFolders(),
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The match could not be started.");
    } finally {
      setBusy(false);
    }
  };

  const stopMatch = async () => {
    if (!activeMatchId) return;
    setBusy(true);
    setError(null);
    try {
      const detail = await matchApi.stopMatch(activeMatchId);
      setSelectedMatch(detail);
      setActiveMatchId(null);
      await refreshMatches(query, folderFilter);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The active match could not be stopped.");
    } finally {
      setBusy(false);
    }
  };

  const openRecord = async (matchId: string) => {
    try {
      await openMatch(matchId, "replay");
      navigateWorkspace("matches");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That match record could not be opened.");
    }
  };

  const returnToLive = async () => {
    if (!activeMatchId) return;
    try {
      await openMatch(activeMatchId, "live");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The active match could not be restored.");
    }
  };

  const createFolder = async (name: string): Promise<boolean> => {
    setFolderBusy(true);
    setFolderError(null);
    try {
      const folder = await matchApi.createFolder(name);
      setStartFolderId(folder.id);
      setFolderFilter(folder.id);
      await Promise.all([
        refreshFolders(),
        refreshMatches(query, folder.id),
      ]);
      return true;
    } catch (caught) {
      setFolderError(caught instanceof Error ? caught.message : "The folder could not be created.");
      return false;
    } finally {
      setFolderBusy(false);
    }
  };

  const assignMatchFolder = async (matchId: string, folderId: string | null) => {
    setAssigningMatchId(matchId);
    setAssignmentError(null);
    try {
      const detail = await matchApi.assignMatchFolder(matchId, folderId);
      if (selectedMatch?.id === matchId) setSelectedMatch(detail);
      await Promise.all([
        refreshFolders(),
        refreshMatches(query, folderFilter),
      ]);
    } catch (caught) {
      setAssignmentError({
        matchId,
        message: caught instanceof Error ? caught.message : "Could not move this record. Try again.",
      });
    } finally {
      setAssigningMatchId(null);
    }
  };

  const emptyHistoryMessage = query.trim()
    ? "No records match this search in the selected folder. Try another player, version, or status."
    : folderFilter === "all"
      ? "No matches have been recorded yet. Start a match to create the first record."
      : folderFilter === "unfiled"
        ? "Every recorded match is filed. Choose a named folder to browse it."
        : `This folder is empty. Select it under New match or move an existing record here.`;

  const showSetup = setupOpen || (!loading && !selectedMatch);
  const sectionTitle = workspaceSection === "matches" ? "Match desk" : workspaceSection === "records" ? "Match library" : "Positional testing";

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <a className="brand" href="#top" onClick={() => navigateWorkspace("matches")} aria-label="Chess Harness match desk">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span>
          <span><strong>Chess Harness</strong><small>Agent research workspace</small></span>
        </a>
        <nav className="workspace-nav" aria-label="Workspace sections">
          <button className={`workspace-nav__button ${workspaceSection === "matches" ? "workspace-nav__button--active" : ""}`} type="button" aria-current={workspaceSection === "matches" ? "page" : undefined} onClick={() => navigateWorkspace("matches")}>
            <LayoutGrid size={18} aria-hidden="true" /><span>Match desk</span>
          </button>
          <button className={`workspace-nav__button ${workspaceSection === "records" ? "workspace-nav__button--active" : ""}`} type="button" aria-current={workspaceSection === "records" ? "page" : undefined} onClick={() => navigateWorkspace("records")}>
            <Library size={18} aria-hidden="true" /><span>Match library</span><span className="nav-count">{allMatchCount}</span>
          </button>
          <button className={`workspace-nav__button ${workspaceSection === "positional-testing" ? "workspace-nav__button--active" : ""}`} type="button" aria-current={workspaceSection === "positional-testing" ? "page" : undefined} onClick={() => navigateWorkspace("positional-testing")}>
            <FlaskConical size={18} aria-hidden="true" /><span>Positional testing</span>
          </button>
        </nav>
        <div className="sidebar-settings">
          <ModelSelector selection={modelSelection} disabled={busy || positionalRunning} onChange={setModelSelection} />
          <div className="environment-mark"><Server size={15} aria-hidden="true" /><span>Local workspace</span><span className="version-mark">v2</span></div>
        </div>
      </aside>

      <div className="app-content">
        <main id="top">
          <header className="workspace-heading">
            <div>
              <h1 ref={headingRef} tabIndex={-1}>{sectionTitle}</h1>
              <p>{workspaceSection === "matches" ? "Every position. Every decision." : workspaceSection === "records" ? "Find a run. Revisit the reasoning." : "One position. One agent. One decision."}</p>
            </div>
            {workspaceSection === "matches" && selectedMatch ? (
              <button className={`button ${showSetup ? "button--secondary" : "button--primary"}`} type="button" aria-expanded={showSetup} aria-controls="match-setup" onClick={() => setSetupOpen((value) => !value)}>
                {showSetup ? <X size={17} aria-hidden="true" /> : <Plus size={17} aria-hidden="true" />}
                {showSetup ? "Match setup" : "New match"}
              </button>
            ) : workspaceSection === "records" ? (
              <button className="button button--primary" type="button" onClick={() => { setSetupOpen(true); navigateWorkspace("matches"); }}><Plus size={17} aria-hidden="true" />New match</button>
            ) : null}
          </header>

          <div hidden={workspaceSection !== "matches"}>
            <div id="match-setup" className="match-setup" hidden={!showSetup}>
              <MatchDocket harnesses={harnesses} whiteId={whiteId} blackId={blackId} folders={folders} folderId={startFolderId} busy={busy || loading} folderBusy={folderBusy} folderError={folderError} onWhiteChange={setWhiteId} onBlackChange={setBlackId} onFolderChange={setStartFolderId} onCreateFolder={createFolder} onStart={startMatch} />
            </div>
            {error ? (
              <div className="error-banner" role="alert">
                <AlertTriangle size={18} aria-hidden="true" /><span><strong>Backend request failed.</strong> {error}</span>
                <button type="button" onClick={() => window.location.reload()}><RotateCcw size={15} aria-hidden="true" />Reload</button>
              </div>
            ) : null}
            {loading ? (
              <div className="loading-state" aria-live="polite"><span className="loading-board" aria-hidden="true" /><h2>Opening your workspace</h2><p>Loading matches and harnesses…</p></div>
            ) : !selectedMatch || !position ? (
              <div className="loading-state"><LayoutGrid size={32} aria-hidden="true" /><h2>Your first match starts here</h2><p>Choose the white and black harnesses above, then start a match to inspect every move.</p></div>
            ) : (
              <>
                {mode === "replay" && activeMatchId ? (
                  <button className="return-live" type="button" onClick={returnToLive}><span className="environment-dot" />Return to active match<ArrowUpRight size={15} aria-hidden="true" /></button>
                ) : null}
                <div className="match-workspace">
                  <div className="board-column">
                    <MatchStatus match={selectedMatch} displayPly={displayPly} replaying={mode === "replay"} currentMove={position.san} canStop={selectedMatch.id === activeMatchId && selectedMatch.status === "running"} busy={busy} onStop={stopMatch} />
                    <Chessboard position={position} flipped={flipped} />
                    <ReplayControls ply={displayPly} maxPly={selectedMatch.moveCount} playing={playing} onChange={(ply) => { setDisplayPly(Math.max(0, Math.min(ply, selectedMatch.moveCount))); setMode("replay"); setPlaying(false); }} onTogglePlaying={() => { if (!playing && displayPly === selectedMatch.moveCount) setDisplayPly(0); setMode("replay"); setPlaying((value) => !value); }} onFlip={() => setFlipped((value) => !value)} />
                    <div className="board-caption"><span>Position {displayPly} of {selectedMatch.moveCount}</span><span>{flipped ? "Black" : "White"} perspective</span></div>
                  </div>
                  <TracePanel events={selectedMatch.traces} activePly={displayPly} onSelectPly={(ply) => { setDisplayPly(Math.max(0, Math.min(ply, selectedMatch.moveCount))); setMode("replay"); setPlaying(false); }} />
                </div>
                <details className="match-details">
                  <summary>Match details<ChevronDown size={15} aria-hidden="true" /><span>{selectedMatch.id}</span></summary>
                  <dl><div><dt>White version</dt><dd>{selectedMatch.white.version}</dd></div><div><dt>Black version</dt><dd>{selectedMatch.black.version}</dd></div><div><dt>Result</dt><dd>{selectedMatch.result ?? "Pending"}</dd></div><div><dt>Termination</dt><dd>{selectedMatch.terminationReason ?? "Match in progress"}</dd></div></dl>
                </details>
              </>
            )}
          </div>

          <div hidden={workspaceSection !== "records"}>
            {error ? <div className="error-banner" role="alert"><AlertTriangle size={18} aria-hidden="true" /><span>{error}</span></div> : null}
            <div className="records-workspace">
              <FolderRail folders={folders} totalMatches={allMatchCount} unfiledCount={unfiledCount} selectedId={folderFilter} creating={folderBusy} createError={folderError} onSelect={setFolderFilter} onCreate={createFolder} />
              <HistoryList matches={matches} total={totalMatches} query={query} selectedId={selectedMatch?.id ?? null} loading={loading} folders={folders} assigningId={assigningMatchId} assignmentError={assignmentError} emptyMessage={emptyHistoryMessage} onQueryChange={setQuery} onOpen={openRecord} onAssignFolder={assignMatchFolder} />
            </div>
          </div>
          <div hidden={workspaceSection !== "positional-testing"}>
            <PositionalTesting modelSelection={modelSelection} running={positionalRunning} onRunningChange={setPositionalRunning} />
          </div>
        </main>
        <footer><span>Chess Harness <span aria-hidden="true">/</span> Agent research</span><span>Backend-verified positions · Public decision traces</span></footer>
      </div>
    </div>
  );
}
