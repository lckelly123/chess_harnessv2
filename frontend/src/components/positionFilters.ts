import type { PositionalTestPosition } from "../api/contracts";

export interface PositionFilters {
  query: string;
  split: string;
  phase: string;
  positionType: string;
  sideToMove: string;
  datasetVersion: string;
  theme: string;
  source: string;
  rating: string;
}

export const EMPTY_POSITION_FILTERS: PositionFilters = {
  query: "", split: "", phase: "", positionType: "", sideToMove: "",
  datasetVersion: "", theme: "", source: "", rating: "",
};

export function tagLabel(value: string) {
  if (value === "train") return "Training";
  if (value === "lichess_game") return "Lichess game";
  if (value === "lichess_puzzle") return "Lichess puzzle";
  const words = value.replace(/([a-z])([A-Z])/g, "$1 $2").replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function filterPositions(positions: PositionalTestPosition[], filters: PositionFilters) {
  const query = filters.query.trim().toLowerCase();
  return positions.filter((position) => {
    for (const field of ["split", "phase", "positionType", "sideToMove", "datasetVersion", "source"] as const) {
      if (filters[field] && position[field] !== filters[field]) return false;
    }
    if (filters.theme && !position.themes.includes(filters.theme)) return false;
    const rating = position.puzzleRating;
    if (filters.rating === "unrated" && rating !== null) return false;
    if (filters.rating && filters.rating !== "unrated") {
      if (rating === null) return false;
      if (filters.rating === "under1400" && rating >= 1400) return false;
      if (filters.rating === "1400to1799" && (rating < 1400 || rating >= 1800)) return false;
      if (filters.rating === "1800plus" && rating < 1800) return false;
    }
    return !query || [position.id, position.sourceGameId, position.name, position.opening ?? "", ...position.themes.map(tagLabel)]
      .join(" ").toLowerCase().includes(query);
  });
}
