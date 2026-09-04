import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { matchApi } from "./api/client";
import type { HarnessVersion, MatchDetail, MatchSummary } from "./api/contracts";
import { Chessboard } from "./components/Chessboard";
import { HistoryList } from "./components/HistoryList";
import { MatchDocket } from "./components/MatchDocket";
import { MatchStatus } from "./components/MatchStatus";
import { ReplayControls } from "./components/ReplayControls";
import { TracePanel } from "./components/TracePanel";

type DeskMode = "live" | "replay";

export default function App() {
  const [harnesses, setHarnesses] = useState<HarnessVersion[]>([]);
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [totalMatches, setTotalMatches] = useState(0);
  const [selectedMatch, setSelectedMatch] = useState<MatchDetail | null>(null);
  const [activeMatchId, setActiveMatchId] = useState<string | null>(null);
  const [whiteId, setWhiteId] = useState("");
  const [blackId, setBlackId] = useState("");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<DeskMode>("live");
  const [displayPly, setDisplayPly] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshMatches = useCallback(async (search = "") => {
    const response = await matchApi.listMatches(search);
    setMatches(response.items);
    setTotalMatches(response.total);
    return response.items;
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
        const [availableHarnesses, availableMatches] = await Promise.all([
          matchApi.listHarnesses(),
          refreshMatches(),
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
  }, [openMatch, refreshMatches]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      refreshMatches(query).catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : "Could not search match records.");
      });
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query, refreshMatches]);

  useEffect(() => {
    if (!activeMatchId || mode !== "live" || selectedMatch?.status !== "running") return;
    const interval = window.setInterval(() => {
      matchApi.getMatch(activeMatchId).then((detail) => {
        setSelectedMatch(detail);
        setDisplayPly(detail.moveCount);
      }).catch(() => setError("Live refresh failed. The last backend snapshot is still shown."));
    }, 3000);
    return () => window.clearInterval(interval);
  }, [activeMatchId, mode, selectedMatch?.status]);

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
      const detail = await matchApi.startMatch({ whiteHarnessId: whiteId, blackHarnessId: blackId });
      setActiveMatchId(detail.id);
      setSelectedMatch(detail);
      setMode("live");
      setDisplayPly(detail.moveCount);
      await refreshMatches(query);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The mock match could not be started.");
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
      await refreshMatches(query);
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

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#top" aria-label="Chess Harness match desk">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span>
          <span><strong>Chess Harness</strong><small>Match desk · v2</small></span>
        </a>
        <div className="environment-mark">
          <span className="environment-dot" />
          Local mock API
        </div>
      </header>

      <main id="top">
        <MatchDocket
          harnesses={harnesses}
          whiteId={whiteId}
          blackId={blackId}
          busy={busy || loading}
          onWhiteChange={setWhiteId}
          onBlackChange={setBlackId}
          onStart={startMatch}
        />

        {error ? (
          <div className="error-banner" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <span><strong>Backend request failed.</strong> {error}</span>
            <button type="button" onClick={() => window.location.reload()}><RotateCcw size={15} aria-hidden="true" /> Reload</button>
          </div>
        ) : null}

        {loading || !selectedMatch || !position ? (
          <div className="loading-state" aria-live="polite">Opening the mock match ledger…</div>
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

        <HistoryList
          matches={matches}
          total={totalMatches}
          query={query}
          selectedId={selectedMatch?.id ?? null}
          loading={loading}
          onQueryChange={setQuery}
          onOpen={openRecord}
        />
      </main>
      <footer>
        <span>Illustrative data only — no chess engine or agent is running.</span>
        <span>Frontend contract: REST snapshots today, event stream later.</span>
      </footer>
    </div>
  );
}
