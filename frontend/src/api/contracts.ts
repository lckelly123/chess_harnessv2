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

export interface GameFolderRef {
  id: string;
  name: string;
}

export interface GameFolder extends GameFolderRef {
  createdAt: string;
  matchCount: number;
}

export interface GameFolderList {
  items: GameFolder[];
  totalMatches: number;
  unfiledCount: number;
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
  currentPlayer: PlayerColor | null;
  currentPhase: string | null;
  terminationReason: string | null;
  folder: GameFolderRef | null;
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
  folderId: string | null;
}

export interface MatchApi {
  listHarnesses(): Promise<HarnessVersion[]>;
  listFolders(): Promise<GameFolderList>;
  createFolder(name: string): Promise<GameFolder>;
  listMatches(query?: string, folderId?: string | null): Promise<MatchList>;
  getMatch(matchId: string): Promise<MatchDetail>;
  startMatch(input: StartMatchInput): Promise<MatchDetail>;
  stopMatch(matchId: string): Promise<MatchDetail>;
  assignMatchFolder(matchId: string, folderId: string | null): Promise<MatchDetail>;
}
