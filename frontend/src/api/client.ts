import type {
  GameFolder,
  GameFolderList,
  HarnessVersion,
  MatchApi,
  MatchDetail,
  MatchList,
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

  return (await response.json()) as T;
}

export const matchApi: MatchApi = {
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
};
