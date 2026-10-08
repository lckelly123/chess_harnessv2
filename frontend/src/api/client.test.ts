import { afterEach, describe, expect, it, vi } from "vitest";
import { matchApi } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("matchApi", () => {
  it("deletes matches, individual runs, and queues with empty success responses", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchMock);
    await expect(matchApi.deleteMatch("match/id")).resolves.toBeUndefined();
    await expect(matchApi.deleteModelRun("run/id")).resolves.toBeUndefined();
    await expect(matchApi.deletePositionQueue("queue/id")).resolves.toBeUndefined();
    expect(fetchMock.mock.calls.map(([path, init]) => [path, init.method])).toEqual([
      ["/api/matches/match%2Fid", "DELETE"],
      ["/api/positional-testing/runs/run%2Fid", "DELETE"],
      ["/api/positional-testing/queues/queue%2Fid", "DELETE"],
    ]);
  });
  it("keeps the backend's recovery message when deletion is refused", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Stop the active queue first." }), { status: 409 })));
    await expect(matchApi.deletePositionQueue("queue-id")).rejects.toMatchObject({ status: 409, message: "Stop the active queue first." });
  });
  it("loads a single pass exchange on demand without modifying its text", async () => {
    const exchange = { input: "  exact prompt\r\n\t雪", output: [' \n{"tool_calls": [invalid\t ', "  repeated  ", "  repeated  "] };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(exchange), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await matchApi.getModelPassExchange("run/id", 2)).toEqual(exchange);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/positional-testing/runs/run%2Fid/passes/2/exchange");
    expect(fetchMock.mock.calls[0][1].method).toBeUndefined();
  });
  it("starts a full-set queue with its configuration and polls or stops by queue ID", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    const input = { name: "Test · prompt v2 雪", split: "test" as const, datasetVersion: "positions-v1", harnessId: "agent-player-3-langgraph-v1", modelSelection: { modelId: "gpt-terra" as const, reasoningEffort: "medium" as const } };
    await matchApi.createPositionQueue(input);
    await matchApi.listPositionQueues();
    await matchApi.getPositionQueue("queue/id");
    await matchApi.stopPositionQueue("queue/id");
    expect(fetchMock.mock.calls[0]).toEqual(["/api/positional-testing/queues", expect.objectContaining({ method: "POST", body: JSON.stringify(input) })]);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/positional-testing/queues");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/positional-testing/queues/queue%2Fid");
    expect(fetchMock.mock.calls[3]).toEqual(["/api/positional-testing/queues/queue%2Fid/stop", expect.objectContaining({ method: "POST" })]);
  });

  it("combines position, run, and full-queue filters and loads a run's passes", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    await matchApi.listModelRuns({ positionId: "position-id", runId: "run-id", queueTag: "queue-id", offset: 30 });
    await matchApi.getModelRun("run-id");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/positional-testing/runs?limit=30&offset=30&position_id=position-id&run_id=run-id&queue_tag=queue-id");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/positional-testing/runs/run-id");
  });
  it("sends combined library filters and requests options from all saved history", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    await matchApi.listModelRuns({ split: "train", datasetVersion: "v1", harness: "retired", model: "offline", analysis: "completed", classification: "blunder", status: "completed", runSource: "queue", sort: "oldest", query: "a & b", offset: 30 });
    const params = new URL(String(fetchMock.mock.calls[0][0]), "http://localhost").searchParams;
    expect(Object.fromEntries(params)).toEqual({ limit: "30", offset: "30", split: "train", dataset_version: "v1", harness: "retired", model: "offline", analysis: "completed", classification: "blunder", status: "completed", run_source: "queue", sort: "oldest", query: "a & b" });
    await matchApi.getModelRunFilters();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/positional-testing/run-filters");
  });
  it.each(["qwen", "gpt-terra"] as const)("includes the requested %s model and medium reasoning on new runs", async (modelId) => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ id: "request-only" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    vi.stubGlobal("fetch", fetchMock);
    const modelSelection = { modelId, reasoningEffort: "medium" as const };
    const matchInput = {
      whiteHarnessId: "agent-player-2-langgraph-v1",
      blackHarnessId: "baseline-direct-submit-langgraph-v1",
      folderId: null,
      modelSelection,
    };
    const positionInput = {
      positionId: "5448280b-9d09-5211-97d3-ff1376d90797",
      harnessId: "agent-player-2-langgraph-v1",
      modelSelection,
    };

    await matchApi.startMatch(matchInput);
    await matchApi.runPositionalTest(positionInput);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/matches", expect.objectContaining({
      method: "POST",
      body: JSON.stringify(matchInput),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/positional-testing/runs", expect.objectContaining({
      method: "POST",
      body: JSON.stringify(positionInput),
    }));
  });

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

  it("loads the PostgreSQL position library", async () => {
    const responseBody = { items: [{ id: "5448280b-9d09-5211-97d3-ff1376d90797" }] };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await matchApi.listPositionalTestPositions();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/positional-testing/positions",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
    expect(response).toEqual(responseBody);
  });

  it("runs one selected harness turn against a saved position", async () => {
    const responseBody = {
      runId: "positional-test-fixed",
      move: { san: "Qxe3+", uci: "d4e3" },
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await matchApi.runPositionalTest({
      positionId: "5448280b-9d09-5211-97d3-ff1376d90797",
      harnessId: "agent-player-1-langgraph-v1",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/positional-testing/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          positionId: "5448280b-9d09-5211-97d3-ff1376d90797",
          harnessId: "agent-player-1-langgraph-v1",
        }),
      }),
    );
    expect(response).toEqual(responseBody);
  });
});
