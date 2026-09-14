"""Tests für die Deckelung der Antwortgrößen.

Die Deckelung ist der eigentliche Zweck dieses Servers gegenüber einem rohen
curl. Zwei Eigenschaften müssen halten: sie greift wirklich, und sie sagt dem
Agenten, dass sie gegriffen hat.
"""

from fastflow_mcp import bounds


def test_clamp_uses_default_maximum_and_floor():
    assert bounds.clamp(None, default=20, maximum=100) == 20
    assert bounds.clamp(50, default=20, maximum=100) == 50
    # Ein Modell fragt gern 10000 an – begrenzen statt ablehnen, sonst folgt
    # eine Wiederholungsschleife.
    assert bounds.clamp(10_000, default=20, maximum=100) == 100
    assert bounds.clamp(0, default=20, maximum=100) == 1
    assert bounds.clamp(-5, default=20, maximum=100) == 1


def test_tail_keeps_the_end_where_the_error_is():
    text = "\n".join(f"Zeile {i}" for i in range(1, 1001))

    result = bounds.tail_lines(text, max_lines=10)

    assert result.truncated is True
    assert result.total_lines == 1000
    assert result.returned_lines == 10
    assert result.text.splitlines()[-1] == "Zeile 1000"
    assert result.text.splitlines()[0] == "Zeile 991"


def test_tail_reports_what_was_dropped():
    result = bounds.tail_lines("\n".join(str(i) for i in range(500)), max_lines=5)

    note = result.as_note()
    assert "5 von 500 Zeilen" in note
    # Eine stillschweigend gekürzte Antwort sieht aus wie das ganze Bild.
    assert note != ""


def test_short_input_is_not_marked_truncated():
    result = bounds.tail_lines("eine\nzwei\ndrei", max_lines=10)

    assert result.truncated is False
    assert result.as_note() == ""
    assert result.returned_lines == 3


def test_byte_cap_wins_over_line_cap():
    # 100 Zeilen à ~200 Bytes = ~20 KB, Deckel bei 1 KB.
    text = "\n".join("x" * 200 for _ in range(100))

    result = bounds.tail_lines(text, max_lines=100, max_bytes=1024)

    assert result.truncated is True
    assert result.returned_bytes <= 1024


def test_byte_cap_never_produces_broken_utf8():
    """Am Byte-Deckel darf kein halbes Mehrbyte-Zeichen entstehen."""
    text = "\n".join("äöü" * 50 for _ in range(50))

    result = bounds.tail_lines(text, max_lines=50, max_bytes=300)

    # Würde hier ein Ersatzzeichen oder ein Dekodierfehler entstehen, schlüge
    # bereits das erneute Kodieren fehl.
    assert result.text.encode("utf-8").decode("utf-8") == result.text
    assert result.returned_bytes <= 300


def test_byte_cap_drops_the_partial_first_line():
    text = "\n".join(f"{i:04d}-" + "y" * 40 for i in range(50))

    result = bounds.tail_lines(text, max_lines=50, max_bytes=200)

    # Jede zurückgegebene Zeile ist vollständig (beginnt mit ihrem Zählerpräfix).
    for line in result.text.splitlines():
        assert line[4] == "-", f"angebrochene Zeile: {line!r}"


def test_head_keeps_the_start_for_cell_output():
    text = "\n".join(f"Zeile {i}" for i in range(1, 101))

    result = bounds.head_lines(text, max_lines=3)

    assert result.text.splitlines() == ["Zeile 1", "Zeile 2", "Zeile 3"]
    assert result.truncated is True
    assert result.total_lines == 100


def test_clip_bytes_for_source_files():
    text = "print('hallo')\n" * 1000

    result = bounds.clip_bytes(text, max_bytes=100)

    assert result.truncated is True
    assert result.returned_bytes <= 100
    assert result.text.startswith("print('hallo')")


def test_empty_input_everywhere():
    for fn, arg in (
        (bounds.tail_lines, 10),
        (bounds.head_lines, 10),
        (bounds.clip_bytes, 10),
    ):
        result = fn("", arg)
        assert result.text == ""
        assert result.truncated is False
        assert result.as_note() == ""
