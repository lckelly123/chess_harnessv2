# Training set 2 — Codex

Rows in `train_2_full.jsonl` (inclusive). **10 positions · 156 passes.**

| Rows | Position | Position ID | Chosen move |
| --- | --- | --- | --- |
| 1–17 | White to move, move 20 | `4d7fc789-d690-532e-8b1c-5de714e779a1` | Be5 |
| 18–36 | White to move, move 22 | `13e0f25d-87cb-54fa-89b6-fda8899289c7` | Rh3 |
| 37–54 | Black to move, move 19 | `4cc38745-b17c-59e8-8650-c743e91b0972` | Be7 |
| 55–64 | Black to move, move 16 | `0d2463eb-8582-55ca-a9ae-00693ed04b37` | Rf8 |
| 65–85 | White to move, move 18 | `f39d5593-04dd-5a57-a10d-a8e5f6881442` | Qg3+ |
| 86–102 | Black to move, move 19 | `eea232f7-d78a-5c54-8eb7-e02e4a5e800a` | Qd4+ |
| 103–107 | Black to move, move 13 | `873c60b9-8ac3-56ff-be92-8c7ba05fcb8a` | Nd5 |
| 108–124 | White to move, move 14 | `7792595d-9048-5586-b586-d47950c35599` | Nc3 |
| 125–146 | Black to move, move 16 | `06a5c34d-c302-576c-bd50-960c40389192` | Bxf3 |
| 147–156 | White to move, move 22 | `846002cd-2338-549d-babd-1b3b306ebea8` | Bxe6 |

Source: `gpt-6-astra` · Harness: `chess_harness` (`agent-player-2-langgraph-v1`).

Saved harness input and authored output preserved. Teacher instructions excluded.

<details>
<summary>Source runs</summary>

- **Rows 1–17 (17 passes):** run `bcddbda1-6c41-4212-b6f1-1478d4b6e758`. Threat assessment, recaptures, and candidate comparison.
  FEN: `r1b1r1k1/pp3ppp/5q2/3p4/1P1P1B2/P2Q3P/5PP1/2R2RK1 w - - 1 20`

- **Rows 18–36 (19 passes):** run `67b517df-cdeb-433d-a2e3-7e633f5c966f`. Candidate revision, mating threats, and alternative defenses.
  FEN: `1r1q1rk1/3pbp1p/pp2p1pQ/8/4b1B1/3R4/2P2PPP/4R1K1 w - - 0 22`

- **Rows 37–54 (18 passes):** run `20c7e48f-d590-41b3-8142-1fea8c88b665`. Defending the d5 pawn and handling queen checks.
  FEN: `3q1rk1/p1p3pp/2Qb1p2/3p4/3P2P1/3BP3/P4PP1/3R2K1 b - - 0 19`

- **Rows 55–64 (10 passes):** run `80b71cc7-d4db-4d84-b74a-7ecd8b25002c`. Reinforcing f7 and testing the central pawn exchange.
  FEN: `r3k1r1/pp3p1p/2n5/2pp4/7P/1P2P3/P1PP2P1/R1B2RK1 b q - 0 16`

- **Rows 65–85 (21 passes):** run `1e42da19-9d82-4417-bcbd-aee30dd0744c`. Answering a queen-rook fork with checks and testing defensive blocks.
  FEN: `r1b2rk1/pp1npp2/3p3P/q1pP4/7P/3Q4/P1P1KnP1/R4BNR w - - 0 18`

- **Rows 86–102 (17 passes):** run `7ce71038-ae8d-4128-a71c-06cf175e1558`. Escaping a queen attack and comparing queen exchanges.
  FEN: `1r4k1/pbp1bp1p/1pn1p1p1/4P3/PP2B3/2q2PQ1/3B2PP/3R1RK1 b - - 0 19`

- **Rows 103–107 (5 passes):** run `d42e0a15-2c79-413f-a05b-b185e0e9eca0`. Knight activity and checking the safety of a rook check.
  FEN: `2kr3r/ppp3pp/2n2n2/8/5B2/2P2P1P/P4PP1/R1K2B1R b - - 0 13`

- **Rows 108–124 (17 passes):** run `7bd00d40-1418-4339-98c7-03c6fed286d8`. Developing with defended pawns and testing tempting captures.
  FEN: `r3k2r/5ppp/p1p1b1n1/4P3/5p2/8/PPP3PP/RNB1R1K1 w kq - 3 14`

- **Rows 125–146 (22 passes):** run `53a7ff67-8542-4061-9011-e5edf1f7fc90`. Resolving an attacked bishop and verifying the exchange outcome.
  FEN: `r4rk1/p1p1qpp1/1p3b1p/nQ5b/8/2P2NPP/PP2PPB1/R1B1R1K1 b - - 3 16`

- **Rows 147–156 (10 passes):** run `5cc56f5c-2786-4621-b82e-ffdeb0259f78`. Defensive simplification versus pawn grabbing and rook activity.
  FEN: `r4r2/pp3p2/3pbp1k/3Bp3/3pP2P/3P2R1/PPP1KP2/7R w - - 2 22`

</details>
