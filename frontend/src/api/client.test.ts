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
      whiteHarnessId: "agent-player-1-langgraph-v1",
      blackHarnessId: "baseline-direct-submit-langgraph-v1",
      folderId: "folder-regression",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/matches",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          whiteHarnessId: "agent-player-1-langgraph-v1",
          blackHarnessId: "baseline-direct-submit-langgraph-v1",
          folderId: "folder-regression",
        }),
      }),
    );
  });

  it("encodes folder filters and unfiled records explicitly", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items: [], total: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await matchApi.listMatches("baseline", "folder-regression");
    await matchApi.listMatches("", null);

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/matches?query=baseline&folder_id=folder-regression",
    );
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/matches?query=&unfiled_only=true",
    );
  });
});
