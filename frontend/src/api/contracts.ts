export type PlayerColor = "white" | "black";
export type MatchStatus = "queued" | "running" | "completed" | "stopped" | "failed";
export type TracePhase = "observe" | "plan" | "act" | "verify";
export type TraceStatus = "complete" | "active" | "failed";

export interface HarnessVersion {
  id: string;
  name: string;
  version: string;
  summary: string;
}

export interface PlayerRef {
  harnessId: string;
  name: string;
  version: string;
  color: PlayerColor;
}

export interface PositionRecord {
  ply: number;
  fen: string;
  san: string;
  player: PlayerColor | null;
  fromSquare: string | null;
  toSquare: string | null;
}

export interface TraceEvent {
  id: string;
  timestamp: string;
  ply: number;
  player: PlayerColor;
  phase: TracePhase;
  status: TraceStatus;
  summary: string;
  detail: string;
}

export interface MatchSummary {
  id: string;
  white: PlayerRef;
  black: PlayerRef;
  status: MatchStatus;
  result: string | null;
  startedAt: string;
  endedAt: string | null;
  currentFen: string;
  moveCount: number;
  lastMove: string | null;
}

export interface MatchDetail extends MatchSummary {
  positions: PositionRecord[];
  traces: TraceEvent[];
}

export interface MatchList {
  items: MatchSummary[];
  total: number;
}

export interface StartMatchInput {
  whiteHarnessId: string;
  blackHarnessId: string;
}

export interface MatchApi {
  listHarnesses(): Promise<HarnessVersion[]>;
  listMatches(query?: string): Promise<MatchList>;
  getMatch(matchId: string): Promise<MatchDetail>;
  startMatch(input: StartMatchInput): Promise<MatchDetail>;
  stopMatch(matchId: string): Promise<MatchDetail>;
}

