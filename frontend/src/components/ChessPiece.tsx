interface ChessPieceProps {
  piece: string;
}

function PieceShape({ kind }: { kind: string }) {
  if (kind === "p") {
    return <><circle cx="32" cy="16" r="8" /><path d="M24 26c0 8-3 13-9 21h34c-6-8-9-13-9-21z" /><path d="M16 47h32l5 10H11z" /></>;
  }
  if (kind === "r") {
    return <><path d="M13 9h9v8h7V9h6v8h7V9h9v17H13z" /><path d="M19 26h26l-3 23H22z" /><path d="M16 49h32l5 8H11z" /></>;
  }
  if (kind === "n") {
    return <><path d="M14 49h37c-2-10-7-17-16-21l7-11-13-9-12 19 9-3c-9 7-13 15-12 25z" /><circle cx="31" cy="17" r="2.2" className="piece-detail" /><path d="M12 49h38l4 8H9z" /></>;
  }
  if (kind === "b") {
    return <><path d="M32 7c8 7 12 13 12 19 0 7-5 12-9 16h10l5 15H14l5-15h10c-5-4-9-9-9-16 0-6 4-12 12-19z" /><path d="m36 15-9 14" className="piece-cut" /><path d="M17 49h30" className="piece-line" /></>;
  }
  if (kind === "q") {
    return <><circle cx="13" cy="15" r="4" /><circle cx="25" cy="10" r="4" /><circle cx="39" cy="10" r="4" /><circle cx="51" cy="15" r="4" /><path d="m14 20 7 24h22l7-24-11 10-7-14-7 14z" /><path d="M18 44h28l6 13H12z" /></>;
  }
  return <><path d="M29 6h6v7h7v6h-7v7h-6v-7h-7v-6h7z" /><path d="M21 32c0-7 5-11 11-11s11 4 11 11c0 5-3 9-6 12h9l6 13H12l6-13h9c-3-3-6-7-6-12z" /></>;
}

export function ChessPiece({ piece }: ChessPieceProps) {
  const isWhite = piece === piece.toUpperCase();
  return (
    <svg
      className={`chess-piece chess-piece--${isWhite ? "white" : "black"}`}
      viewBox="0 0 64 64"
      aria-hidden="true"
      focusable="false"
    >
      <g className="piece-body">
        <PieceShape kind={piece.toLowerCase()} />
      </g>
    </svg>
  );
}

