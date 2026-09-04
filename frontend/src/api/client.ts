import type { MatchApi, MatchDetail, MatchList, StartMatchInput, HarnessVersion } from "./contracts";

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
  listMatches: (query = "") => request<MatchList>(`/api/matches?query=${encodeURIComponent(query)}`),
  getMatch: (matchId) => request<MatchDetail>(`/api/matches/${encodeURIComponent(matchId)}`),
  startMatch: (input: StartMatchInput) =>
    request<MatchDetail>("/api/matches", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  stopMatch: (matchId) =>
    request<MatchDetail>(`/api/matches/${encodeURIComponent(matchId)}/stop`, { method: "POST" }),
};

