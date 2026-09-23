export type PlayerColor = "white" | "black";
export type MatchStatus = "queued" | "running" | "completed" | "stopped" | "failed";
export type TracePhase = "observe" | "plan" | "act" | "verify";
export type TraceStatus = "complete" | "active" | "failed";

// Backend allowlisted model selection, resolved once per run.
export interface ModelSelection {
  modelId: "qwen" | "gpt-terra";
  reasoningEffort: "medium";
}

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

export interface PositionalTestPosition {
  id: string;
  name: string;
  datasetVersion: string;
  split: "train" | "test";
  phase: "opening" | "middlegame" | "endgame";
  positionType: "quiet" | "tactical";
  source: "lichess_game" | "lichess_puzzle";
  sourceGameId: string;
  sourceUrl: string;
  opening: string | null;
  themes: string[];
  puzzleRating: number | null;
  sideToMove: PlayerColor;
  moveCount: number;
  position: PositionRecord;
}

export interface PositionalTestPositionList {
  items: PositionalTestPosition[];
}

export interface RunPositionalTestInput {
  positionId: string;
  harnessId: string;
  modelSelection?: ModelSelection;
}

export interface PositionalTestMove {
  san: string;
  uci: string;
  fromSquare: string;
  toSquare: string;
  promotion: string | null;
  isCapture: boolean;
  givesCheck: boolean;
  isCastling: boolean;
  isEnPassant: boolean;
}

export interface PositionalTestRun {
  runId: string;
  positionId: string;
  positionName: string;
  harnessId: string;
  harnessName: string;
  harnessVersion: string;
  model: string;
  side: PlayerColor;
  ply: number;
  move: PositionalTestMove;
  justification: string;
  defenseReport: string | null;
  attackReport: string | null;
}

export interface ModelRun {
  id: string;
  positionId: string;
  model: string;
  harness: string;
  config: Record<string, unknown>;
  status: "running" | "completed" | "failed";
  finalMoveUci: string | null;
  cpLoss: number | null;
  classification: string | null;
  expectedPointsLoss: number | null;
  betterMoves: Record<string, unknown>[] | null;
  evaluation: Record<string, unknown> | null;
  error: string | null;
  startedAt: string;
  finishedAt: string | null;
}

export interface PassToolCall {
  call_id: string | null;
  tool_name: string;
  arguments: unknown;
  result: unknown;
  error: string | null;
  executed: boolean;
  rolled_back?: boolean;
  board_context?: Record<string, unknown>;
}

export interface ModelRunPass {
  runId: string;
  passNumber: number;
  phase: string;
  toolCalls: PassToolCall[];
  workingNotes: string | null;
  status: ModelRun["status"];
  error: string | null;
  startedAt: string;
  finishedAt: string | null;
}

export interface ModelRunDetail extends ModelRun { passes: ModelRunPass[] }
export interface ModelRunList { items: ModelRun[]; total: number }
export interface ModelRunFilters { positionId?: string; runId?: string; offset?: number }

export interface StartMatchInput {
  whiteHarnessId: string;
  blackHarnessId: string;
  folderId: string | null;
  modelSelection?: ModelSelection;
}

export interface CreatePositionQueueInput {
  split: "train" | "test";
  datasetVersion: string;
  harnessId: string;
  modelSelection: ModelSelection;
}

export interface PositionQueueSummary {
  id: string;
  datasetVersion: string;
  split: "train" | "test";
  harnessId: string;
  harnessName: string;
  harnessVersion: string;
  modelSelection: ModelSelection;
  status: "queued" | "running" | "stopping" | "completed" | "stopped";
  total: number;
  completed: number;
  failed: number;
  pending: number;
  running: number;
  skipped: number;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface PositionQueueItem {
  queueId: string;
  ordinal: number;
  positionId: string;
  runId: string | null;
  status: "queued" | "running" | "completed" | "failed" | "skipped";
  phase: string;
  positionType: string;
  finalMoveUci: string | null;
  classification: string | null;
  failureStage: string | null;
  error: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface PositionQueueDetail extends PositionQueueSummary { items: PositionQueueItem[] }
export interface PositionQueueList { items: PositionQueueSummary[] }

export interface MatchApi {
  listPositionQueues(): Promise<PositionQueueList>;
  getPositionQueue(queueId: string): Promise<PositionQueueDetail>;
  createPositionQueue(input: CreatePositionQueueInput): Promise<PositionQueueDetail>;
  stopPositionQueue(queueId: string): Promise<PositionQueueDetail>;
  listHarnesses(): Promise<HarnessVersion[]>;
  listFolders(): Promise<GameFolderList>;
  createFolder(name: string): Promise<GameFolder>;
  listMatches(query?: string, folderId?: string | null): Promise<MatchList>;
  getMatch(matchId: string): Promise<MatchDetail>;
  startMatch(input: StartMatchInput): Promise<MatchDetail>;
  stopMatch(matchId: string): Promise<MatchDetail>;
  assignMatchFolder(matchId: string, folderId: string | null): Promise<MatchDetail>;
  listPositionalTestPositions(): Promise<PositionalTestPositionList>;
  runPositionalTest(input: RunPositionalTestInput): Promise<PositionalTestRun>;
  listModelRuns(filters?: ModelRunFilters): Promise<ModelRunList>;
  getModelRun(runId: string): Promise<ModelRunDetail>;
}
