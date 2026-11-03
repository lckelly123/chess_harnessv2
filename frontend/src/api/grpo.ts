import { ApiError } from "./client";
import type { ModelSelection } from "./contracts";

export interface GrpoTrajectory {
  trajectory: number;
  status: "pending" | "running" | "completed" | "failed" | "stopped" | "interrupted";
  cpLoss: number | null;
  rejectedModelCalls: number;
  toolCounts: Record<string, number>;
}

export interface GrpoGroup {
  name: string;
  status: "preparing" | "running" | "completed" | "stopped" | "failed" | "interrupted";
  positionId: string;
  harnessId: string;
  modelName: string;
  currentTrajectory: number | null;
  currentCall: number;
  completedTrajectories: number;
  totalTrajectories: number;
  outputDirectory: string;
  stopping: boolean;
  error: string | null;
  trajectories: GrpoTrajectory[];
}

export interface GrpoStatus {
  workerOnline: boolean;
  workerMessage: string | null;
  activeRun: GrpoGroup | null;
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/grpo${path}`, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : "The GRPO collection request failed. Try again.";
    throw new ApiError(detail, response.status);
  }
  return data as T;
}

export const grpoApi = {
  status: () => request<GrpoStatus>("/status"),
  start: (input: { name: string; positionId: string; harnessId: string; modelSelection: ModelSelection }) => request<GrpoGroup>("/runs", input),
  group: (name: string) => request<GrpoGroup>(`/runs/${encodeURIComponent(name)}`),
  stop: (name: string) => request<GrpoGroup>(`/runs/${encodeURIComponent(name)}/stop`, {}),
};

export function grpoActive(group: GrpoGroup | null): boolean {
  return group?.status === "preparing" || group?.status === "running";
}
