interface ChessPieceProps {
  piece: string;
}

function PieceBase({ compact = false }: { compact?: boolean }) {
  return (
    <g transform={compact ? "translate(3.2 0) scale(.9 1)" : undefined}>
      <path d="M21 46c3-1.5 6.7-2 11-2s8 .5 11 2l3 5H18z" />
      <path d="M18 51h28c2 0 3.3 1.2 3.8 3L51 58H13l1.2-4c.5-1.8 1.8-3 3.8-3Z" />
      <path d="M18 54.5h28" className="piece-line" />
    </g>
  );
}

function PieceShape({ kind }: { kind: string }) {
  switch (kind) {
    case "p":
      return <>
        <path d="M27 30c.5 7-1.5 11.5-6 16h22c-4.5-4.5-6.5-9-6-16Z" />
        <path d="M25 26h14l2 5H23z" />
        <circle cx="32" cy="18.5" r="8" />
        <PieceBase compact />
      </>;
    case "r":
      return <>
        <path d="M22 27h20l-1 14 4 6H19l4-6z" />
        <path d="M14 11h8v8h6v-8h8v8h6v-8h8v15l-7 5H21l-7-5Z" />
        <path d="M20 26h24M24 41h16" className="piece-line" />
        <PieceBase />
      </>;
    case "n":
      return <>
        <path d="M17 47c-.5-7 2-12 8-18l-7 4c-2 1-4 0-5.5-2L10 27l9-11 5-2 1-7 7 6c8-1 14 5 16 13 2 7 0 15 1 21Z" />
        <path d="M32 17c7 4 9 9 7 15-1 4-4 8-4 12M24 34c-3 4-4 7-4 10M14 27l4 1" className="piece-line" />
        <path d="m24 22 4-2" className="piece-eye" />
        <PieceBase />
      </>;
    case "b":
      return <>
        <path d="M28 35c1 5-.5 8-5 12h18c-4.5-4-6-7-5-12Z" />
        <path d="M32 12c-4 5-12 10-12 17 0 6 5 10 12 10s12-4 12-10c0-7-8-12-12-17Z" />
        <path d="m35.5 19-8 10M26 34h12" className="piece-line" />
        <circle cx="32" cy="9" r="3" />
        <PieceBase />
      </>;
    case "q":
      return <>
        <path d="M23 34c2 5 1 9-2 13h22c-3-4-4-8-2-13Z" />
        <path d="m13 19 8 7 2-13 6 12 3-15 3 15 6-12 2 13 8-7-8 18H21Z" />
        <path d="M23 32h18M25 41h14" className="piece-line" />
        <circle cx="12" cy="16" r="2.8" />
        <circle cx="22" cy="10" r="2.8" />
        <circle cx="32" cy="7" r="2.8" />
        <circle cx="42" cy="10" r="2.8" />
        <circle cx="52" cy="16" r="2.8" />
        <PieceBase />
      </>;
    default:
      return <>
        <path d="M24 34c2 4.5 1 8.5-3 13h22c-4-4.5-5-8.5-3-13Z" />
        <path d="M32 21c-7-8-17-3-16 5 .5 5 4 8 8 11h16c4-3 7.5-6 8-11 1-8-9-13-16-5Z" />
        <path d="M29 5h6v6h6v6h-6v7h-6v-7h-6v-6h6Z" />
        <path d="M32 25v8M24 33h16M25 41h14" className="piece-line" />
        <PieceBase />
      </>;
  }
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
