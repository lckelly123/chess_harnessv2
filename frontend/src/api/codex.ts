import { ApiError } from "./client";
import type { PositionalTestRun } from "./contracts";

export const CODEX_TRAINING_ID = "codex-training";

export interface CodexWorkerStatus {
  configured: boolean;
  online: boolean;
  model: string | null;
  reasoning_effort: string | null;
  active_run_id: string | null;
}

export interface CodexJob {
  run_id: string;
  position_id: string;
  status: "starting" | "waiting" | "processing" | "completed" | "failed" | "cancelled";
  pass_number: number;
  progress: string;
  stopping: boolean;
  error: string | null;
  result: PositionalTestRun | null;
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/codex-training${path}`, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(data?.detail ?? "Codex worker could not be reached.", response.status);
  return data as T;
}

export const codexApi = {
  worker: () => request<CodexWorkerStatus>("/worker"),
  start: (positionId: string) => request<CodexJob>("/jobs", { position_id: positionId }),
  job: (runId: string) => request<CodexJob>(`/jobs/${encodeURIComponent(runId)}`),
  stop: (runId: string) => request<CodexJob>(`/jobs/${encodeURIComponent(runId)}/stop`, {}),
};
