import { afterEach, describe, expect, it, vi } from "vitest";
import { matchApi } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("matchApi", () => {
  it("sends the typed start-match contract as camelCase JSON", async () => {
    const responseBody = { id: "match-test", status: "running" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await matchApi.startMatch({
      whiteHarnessId: "agent-player-1-graph",
      blackHarnessId: "material-baseline",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/matches",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          whiteHarnessId: "agent-player-1-graph",
          blackHarnessId: "material-baseline",
        }),
      }),
    );
  });
});

