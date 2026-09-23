import { describe, expect, it } from "vitest";
import type { PositionalTestPosition } from "../api/contracts";
import { EMPTY_POSITION_FILTERS, filterPositions, tagLabel } from "./positionFilters";

const position: PositionalTestPosition = {
  id: "quiet-train", name: "Middlegame · move 20", datasetVersion: "v1",
  split: "train", phase: "middlegame", positionType: "quiet", sideToMove: "white",
  source: "lichess_game", sourceGameId: "game0001", sourceUrl: "https://lichess.org/game0001",
  opening: "Sicilian Defense", themes: [], puzzleRating: null, moveCount: 38,
  position: { ply: 38, fen: "", san: "Re8", player: "black", fromSquare: "f8", toSquare: "e8" },
};
const positions: PositionalTestPosition[] = [
  position,
  { ...position, id: "quiet-test", split: "test", sideToMove: "black" },
  { ...position, id: "puzzle-low", source: "lichess_puzzle", positionType: "tactical", phase: "endgame", puzzleRating: 1399, themes: ["quietMove", "pin"] },
  { ...position, id: "puzzle-mid", source: "lichess_puzzle", positionType: "tactical", phase: "endgame", puzzleRating: 1400, themes: ["pin"] },
  { ...position, id: "puzzle-high", datasetVersion: "v2", split: "test", source: "lichess_puzzle", positionType: "tactical", puzzleRating: 1800, themes: ["fork"] },
];

describe("position library filtering", () => {
  it("combines set, phase, type and color rather than matching any tag", () => {
    const result = filterPositions(positions, { ...EMPTY_POSITION_FILTERS, split: "test", phase: "middlegame", positionType: "quiet", sideToMove: "black" });
    expect(result.map((item) => item.id)).toEqual(["quiet-test"]);
  });

  it("filters dataset, source and themes together", () => {
    const result = filterPositions(positions, { ...EMPTY_POSITION_FILTERS, datasetVersion: "v2", source: "lichess_puzzle", theme: "fork" });
    expect(result.map((item) => item.id)).toEqual(["puzzle-high"]);
    expect(filterPositions(positions, { ...EMPTY_POSITION_FILTERS, positionType: "quiet", theme: "pin" })).toEqual([]);
  });

  it("searches opening names, position IDs and readable theme labels", () => {
    expect(filterPositions(positions, { ...EMPTY_POSITION_FILTERS, query: " SICILIAN " })).toHaveLength(5);
    expect(filterPositions(positions, { ...EMPTY_POSITION_FILTERS, query: "quiet move" }).map((item) => item.id)).toEqual(["puzzle-low"]);
    expect(filterPositions(positions, { ...EMPTY_POSITION_FILTERS, query: "quiet-test" }).map((item) => item.id)).toEqual(["quiet-test"]);
  });

  it("keeps unrated quiet positions out of numeric puzzle-rating bands", () => {
    expect(filterPositions(positions, { ...EMPTY_POSITION_FILTERS, rating: "under1400" }).map((item) => item.id)).toEqual(["puzzle-low"]);
    expect(filterPositions(positions, { ...EMPTY_POSITION_FILTERS, rating: "1400to1799" }).map((item) => item.id)).toEqual(["puzzle-mid"]);
    expect(filterPositions(positions, { ...EMPTY_POSITION_FILTERS, rating: "1800plus" }).map((item) => item.id)).toEqual(["puzzle-high"]);
    expect(filterPositions(positions, { ...EMPTY_POSITION_FILTERS, rating: "unrated" })).toHaveLength(2);
    expect(filterPositions(positions, EMPTY_POSITION_FILTERS)).toHaveLength(5);
  });

  it("labels the stored classifications without changing their values", () => {
    expect(tagLabel("train")).toBe("Training");
    expect(tagLabel("quietMove")).toBe("Quiet Move");
    expect(tagLabel("lichess_puzzle")).toBe("Lichess puzzle");
  });
});
