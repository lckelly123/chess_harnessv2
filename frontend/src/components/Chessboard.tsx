import type { PositionRecord } from "../api/contracts";
import { ChessPiece } from "./ChessPiece";

const PIECE_LABELS: Record<string, string> = {
  K: "white king", Q: "white queen", R: "white rook", B: "white bishop", N: "white knight", P: "white pawn",
  k: "black king", q: "black queen", r: "black rook", b: "black bishop", n: "black knight", p: "black pawn",
};

const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];

interface Square {
  coordinate: string;
  piece: string | null;
  isLight: boolean;
}

function parseFen(fen: string): Square[] {
  const rows = fen.split(" ")[0].split("/");
  return rows.flatMap((row, rowIndex) => {
    const rank = 8 - rowIndex;
    const pieces: (string | null)[] = [];
    for (const token of row) {
      const empties = Number(token);
      if (Number.isNaN(empties)) {
        pieces.push(token);
      } else {
        pieces.push(...Array.from({ length: empties }, () => null));
      }
    }
    return pieces.map((piece, fileIndex) => ({
      coordinate: `${FILES[fileIndex]}${rank}`,
      piece,
      isLight: (rowIndex + fileIndex) % 2 === 0,
    }));
  });
}

interface ChessboardProps {
  position: PositionRecord;
  flipped: boolean;
}

export function Chessboard({ position, flipped }: ChessboardProps) {
  const squares = parseFen(position.fen);
  if (flipped) squares.reverse();

  return (
    <div className="board-shell">
      <div className="board" role="grid" aria-label={`Chess position after ${position.san}`}>
        {squares.map((square) => {
          const changed = square.coordinate === position.fromSquare || square.coordinate === position.toSquare;
          const isEdgeFile = flipped ? square.coordinate[0] === "h" : square.coordinate[0] === "a";
          const isEdgeRank = flipped ? square.coordinate[1] === "8" : square.coordinate[1] === "1";
          return (
            <div
              className={`board-square ${square.isLight ? "board-square--light" : "board-square--dark"}${changed ? " board-square--changed" : ""}`}
              key={square.coordinate}
              role="gridcell"
              aria-label={`${square.coordinate}${square.piece ? ` ${PIECE_LABELS[square.piece]}` : " empty"}`}
            >
              {square.piece ? <ChessPiece piece={square.piece} /> : null}
              {isEdgeFile ? <span className="rank-label">{square.coordinate[1]}</span> : null}
              {isEdgeRank ? <span className="file-label">{square.coordinate[0]}</span> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
