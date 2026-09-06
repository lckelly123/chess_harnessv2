import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { matchApi } from "./api/client";
import type { GameFolder, HarnessVersion, MatchDetail, MatchSummary } from "./api/contracts";
import { Chessboard } from "./components/Chessboard";
import { FolderRail } from "./components/FolderRail";
import { HistoryList } from "./components/HistoryList";
import { MatchDocket } from "./components/MatchDocket";
import { MatchStatus } from "./components/MatchStatus";
import { ReplayControls } from "./components/ReplayControls";
import { TracePanel } from "./components/TracePanel";

type DeskMode = "live" | "replay";
type FolderFilter = "all" | "unfiled" | string;

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

  const visibleTraces = useMemo(
    () => selectedMatch?.traces.filter((event) => event.ply <= displayPly) ?? [],
    [displayPly, selectedMatch],
  );

  const startMatch = async () => {
    setBusy(true);
    setError(null);
    try {
      const detail = await matchApi.startMatch({
        whiteHarnessId: whiteId,
        blackHarnessId: blackId,
        folderId: startFolderId || null,
      });
      setActiveMatchId(detail.id);
      setSelectedMatch(detail);
      setMode("live");
      setDisplayPly(detail.moveCount);
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

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#top" aria-label="Chess Harness match desk">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span>
          <span><strong>Chess Harness</strong><small>Match desk · v2</small></span>
        </a>
        <div className="environment-mark">
          <span className="environment-dot" />
          Local agent runtime
        </div>
      </header>

      <main id="top">
        <MatchDocket
          harnesses={harnesses}
          whiteId={whiteId}
          blackId={blackId}
          folders={folders}
          folderId={startFolderId}
          busy={busy || loading}
          folderBusy={folderBusy}
          folderError={folderError}
          onWhiteChange={setWhiteId}
          onBlackChange={setBlackId}
          onFolderChange={setStartFolderId}
          onCreateFolder={createFolder}
          onStart={startMatch}
        />

        {error ? (
          <div className="error-banner" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <span><strong>Backend request failed.</strong> {error}</span>
            <button type="button" onClick={() => window.location.reload()}><RotateCcw size={15} aria-hidden="true" /> Reload</button>
          </div>
        ) : null}

        {loading ? (
          <div className="loading-state" aria-live="polite">Opening the match ledger…</div>
        ) : !selectedMatch || !position ? (
          <div className="loading-state">No matches yet. Choose two harnesses to begin.</div>
        ) : (
          <>
            {mode === "replay" && activeMatchId && selectedMatch.id !== activeMatchId ? (
              <button className="return-live" type="button" onClick={returnToLive}>
                <span className="environment-dot" /> Return to active match
              </button>
            ) : null}
            <div className="match-workspace">
              <div className="board-column">
                <MatchStatus
                  match={selectedMatch}
                  displayPly={displayPly}
                  replaying={mode === "replay"}
                  currentMove={position.san}
                  canStop={mode === "live" && selectedMatch.id === activeMatchId && selectedMatch.status === "running"}
                  busy={busy}
                  onStop={stopMatch}
                />
                <Chessboard position={position} flipped={flipped} />
                <ReplayControls
                  ply={displayPly}
                  maxPly={selectedMatch.moveCount}
                  playing={playing}
                  onChange={(ply) => { setDisplayPly(Math.max(0, Math.min(ply, selectedMatch.moveCount))); setPlaying(false); }}
                  onTogglePlaying={() => {
                    if (!playing && displayPly === selectedMatch.moveCount) setDisplayPly(0);
                    setPlaying((value) => !value);
                  }}
                  onFlip={() => setFlipped((value) => !value)}
                />
              </div>
              <TracePanel
                events={visibleTraces}
                activePly={displayPly}
                onSelectPly={(ply) => { setDisplayPly(ply); setMode("replay"); setPlaying(false); }}
              />
            </div>
          </>
        )}

        <div className="records-workspace">
          <FolderRail
            folders={folders}
            totalMatches={allMatchCount}
            unfiledCount={unfiledCount}
            selectedId={folderFilter}
            creating={folderBusy}
            createError={folderError}
            onSelect={setFolderFilter}
            onCreate={createFolder}
          />
          <HistoryList
            matches={matches}
            total={totalMatches}
            query={query}
            selectedId={selectedMatch?.id ?? null}
            loading={loading}
            folders={folders}
            assigningId={assigningMatchId}
            assignmentError={assignmentError}
            emptyMessage={emptyHistoryMessage}
            onQueryChange={setQuery}
            onOpen={openRecord}
            onAssignFolder={assignMatchFolder}
          />
        </div>
      </main>
      <footer>
        <span>Authoritative chess state and agent execution run in the local backend.</span>
        <span>Frontend contract: REST snapshots · detailed execution traces in LangSmith.</span>
      </footer>
    </div>
  );
}
