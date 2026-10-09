import type {
  GameFolder,
  GameFolderList,
  HarnessVersion,
  LoadedModelList,
  MatchApi,
  MatchDetail,
  MatchList,
  ModelRunList,
  ModelRunFilterOptions,
  ModelRunDetail,
  ModelPassExchange,
  PositionQueueDetail,
  PositionQueueList,
  PositionalTestPositionList,
  PositionalTestRun,
  RunPositionalTestInput,
  StartMatchInput,
} from "./contracts";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(payload?.detail ?? `Request failed with status ${response.status}.`, response.status);
  }

  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const matchApi: MatchApi = {
  listLoadedModels: (server) => request<LoadedModelList>(`/api/models?server=${server}`),
  listPositionQueues: () => request<PositionQueueList>("/api/positional-testing/queues"),
  getPositionQueue: (id) => request<PositionQueueDetail>(`/api/positional-testing/queues/${encodeURIComponent(id)}`),
  createPositionQueue: (input) => request<PositionQueueDetail>("/api/positional-testing/queues", { method: "POST", body: JSON.stringify(input) }),
  stopPositionQueue: (id) => request<PositionQueueDetail>(`/api/positional-testing/queues/${encodeURIComponent(id)}/stop`, { method: "POST" }),
  deletePositionQueue: (id) => request<void>(`/api/positional-testing/queues/${encodeURIComponent(id)}`, { method: "DELETE" }),
  listHarnesses: () => request<HarnessVersion[]>("/api/harnesses"),
  listFolders: () => request<GameFolderList>("/api/folders"),
  createFolder: (name) =>
    request<GameFolder>("/api/folders", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  listMatches: (query = "", folderId) => {
    const parameters = new URLSearchParams({ query });
    if (typeof folderId === "string") parameters.set("folder_id", folderId);
    if (folderId === null) parameters.set("unfiled_only", "true");
    return request<MatchList>(`/api/matches?${parameters.toString()}`);
  },
  getMatch: (matchId) => request<MatchDetail>(`/api/matches/${encodeURIComponent(matchId)}`),
  deleteMatch: (matchId) => request<void>(`/api/matches/${encodeURIComponent(matchId)}`, { method: "DELETE" }),
  startMatch: (input: StartMatchInput) =>
    request<MatchDetail>("/api/matches", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  stopMatch: (matchId) =>
    request<MatchDetail>(`/api/matches/${encodeURIComponent(matchId)}/stop`, { method: "POST" }),
  assignMatchFolder: (matchId, folderId) =>
    request<MatchDetail>(`/api/matches/${encodeURIComponent(matchId)}/folder`, {
      method: "PATCH",
      body: JSON.stringify({ folderId }),
    }),
  listPositionalTestPositions: () =>
    request<PositionalTestPositionList>("/api/positional-testing/positions"),
  listModelRuns: (filters = {}) => {
    const parameters = new URLSearchParams({ limit: "30", offset: String(filters.offset ?? 0) });
    if (filters.positionId) parameters.set("position_id", filters.positionId);
    if (filters.runId) parameters.set("run_id", filters.runId);
    if (filters.queueTag) parameters.set("queue_tag", filters.queueTag);
    for (const [key, value] of Object.entries({
      query: filters.query, split: filters.split, dataset_version: filters.datasetVersion,
      harness: filters.harness, model: filters.model, status: filters.status,
      analysis: filters.analysis, classification: filters.classification,
      run_source: filters.runSource, sort: filters.sort,
    })) {
      if (value) parameters.set(key, value);
    }
    return request<ModelRunList>(`/api/positional-testing/runs?${parameters}`);
  },
  getModelRunFilters: () => request<ModelRunFilterOptions>("/api/positional-testing/run-filters"),
  getModelRun: (runId) => request<ModelRunDetail>(`/api/positional-testing/runs/${encodeURIComponent(runId)}`),
  deleteModelRun: (runId) => request<void>(`/api/positional-testing/runs/${encodeURIComponent(runId)}`, { method: "DELETE" }),
  getModelPassExchange: (runId, passNumber) => request<ModelPassExchange>(`/api/positional-testing/runs/${encodeURIComponent(runId)}/passes/${passNumber}/exchange`),
  runPositionalTest: (input: RunPositionalTestInput) =>
    request<PositionalTestRun>("/api/positional-testing/runs", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};
