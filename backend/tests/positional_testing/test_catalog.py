from pathlib import Path

from positional_testing.catalog import get_saved_position, list_saved_positions


def test_reads_saved_pgn_as_a_selectable_final_position() -> None:
    positions = list_saved_positions()

    assert len(positions) == 1
    saved = positions[0]
    assert saved.id == "before_queen_blunder"
    assert saved.name == "Agent Player 1 Queen Blunder Test"
    assert saved.source_file == "before_queen_blunder.pgn"
    assert saved.side_to_move == "black"
    assert saved.move_count == 23
    assert (
        saved.position.fen
        == "2r1kb1r/p1p1pppp/2p5/8/3q4/2N1B3/PPP2PPP/R3K2R b KQk - 1 12"
    )
    assert saved.position.san == "Be3"
    assert saved.position.from_square == "c1"
    assert saved.position.to_square == "e3"


def test_missing_position_directory_is_an_empty_catalog() -> None:
    assert list_saved_positions(Path("positional_testing/does-not-exist")) == []


def test_get_saved_position_retains_the_source_pgn_for_a_turn() -> None:
    document = get_saved_position("before_queen_blunder")

    assert document is not None
    assert document.position.id == "before_queen_blunder"
    assert '[Event "Agent Player 1 Queen Blunder Test"]' in document.pgn
    assert "10. Bxa6 Qxd4 11. Bxc8 Rxc8 12. Be3" in document.pgn


def test_get_saved_position_does_not_resolve_outside_the_catalog() -> None:
    assert get_saved_position("../before_queen_blunder") is None
