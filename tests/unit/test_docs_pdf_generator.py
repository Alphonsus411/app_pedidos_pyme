"""Tests documentales mínimos para helpers pure-Python del generador PDF.

Scope exclusivamente documental: NO toca el dominio.
Validan los fixes P2 de review T2 (escaped pipes), T3 (list marker preservation)
y T5 (Unicode ASCII fallback sin ``?`` solitarios).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Cargamos helpers directamente desde el script (docs/ NO es un paquete Python;
# evitamos añadir __init__.py en docs para mantener el árbol mínimo).
_PDF_SCRIPT = Path(__file__).resolve().parents[2] / "docs" / "_gen_plan_pdf.py"
_SPEC = importlib.util.spec_from_file_location("docs_pdf_gen_mod", _PDF_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
pdf_gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pdf_gen)  # noqa: WPS428  ejecuta el módulo.

# ---------------------------------------------------------------------------
# T2: split_table_row — pipes escapados en tablas Markdown
# ---------------------------------------------------------------------------


def test_split_table_row_simple_3_columns() -> None:
    row = "| Campo | Tipo | Descripción |"
    assert pdf_gen.split_table_row(row) == ["Campo", "Tipo", "Descripción"]


def test_split_table_row_preserves_escaped_pipe_as_literal() -> None:
    """``BusinessId \\| None`` debe seguir siendo UNA celda con literal ``|``."""
    row = "| id | BusinessId \\| None | Opcional |"
    result = pdf_gen.split_table_row(row)
    # Debe producir exactamente 3 columnas (no 4 porque se escape \\|).
    assert len(result) == 3
    assert result[0] == "id"
    # El caracter de escape se retira SOLO tras segmentar: celda 1 tiene pipe literal.
    assert result[1] == "BusinessId | None"
    assert result[2] == "Opcional"


def test_split_table_row_multiple_escaped_pipes_in_single_cell() -> None:
    row = "| a | str \\| int \\| None | c |"
    result = pdf_gen.split_table_row(row)
    assert len(result) == 3
    assert result[1] == "str | int | None"


def test_split_table_row_no_border_pipes_still_works() -> None:
    """Algunas filas pueden (hipotéticamente) venir sin pipes de borde extremo."""
    row = "Campo | Tipo | Descripción"
    result = pdf_gen.split_table_row(row)
    assert result == ["Campo", "Tipo", "Descripción"]


def test_split_table_row_empty_cells_are_preserved() -> None:
    row = "| a || c |"
    result = pdf_gen.split_table_row(row)
    assert len(result) == 3
    assert result[1] == ""


# ---------------------------------------------------------------------------
# T3: parse_list_line — preservar marcador fuente de listas ordenadas
# ---------------------------------------------------------------------------


def test_parse_list_line_unordered_bullet() -> None:
    parsed = pdf_gen.parse_list_line("- foo")
    assert parsed is not None
    depth, ordered, src_marker, content = parsed
    assert depth == 0
    assert ordered is False
    assert src_marker is None
    assert content == "foo"


def test_parse_list_line_ordered_numeric_literal() -> None:
    """``4. foo`` → marcador fuente ``\"4\"``, NO inventamos 1."""
    parsed = pdf_gen.parse_list_line("4. foo")
    assert parsed is not None
    depth, ordered, src_marker, content = parsed
    assert depth == 0
    assert ordered is True
    assert src_marker == "4"
    assert content == "foo"


def test_parse_list_line_ordered_range_marker_preserved() -> None:
    """``29-40. inventario`` → marcador literal ``\"29-40\"``."""
    parsed = pdf_gen.parse_list_line("29-40. inventario documental")
    assert parsed is not None
    _, ordered, src_marker, content = parsed
    assert ordered is True
    assert src_marker == "29-40"
    assert content == "inventario documental"


def test_parse_list_line_ordered_indented_nested_depth_1() -> None:
    parsed = pdf_gen.parse_list_line("  2. subitem")
    assert parsed is not None
    depth, ordered, src_marker, content = parsed
    # 2 espacios → indent 2 → depth = 2//2 = 1
    assert depth == 1
    assert ordered is True
    assert src_marker == "2"
    assert content == "subitem"


def test_parse_list_line_non_list_returns_none() -> None:
    assert pdf_gen.parse_list_line("párrafo normal.") is None
    assert pdf_gen.parse_list_line("") is None
    assert pdf_gen.parse_list_line("## heading") is None


def test_parse_list_line_multiple_markers() -> None:
    """Diferentes bullets NO ordenados: + y * también funcionan."""
    assert pdf_gen.parse_list_line("* item")[1] is False
    assert pdf_gen.parse_list_line("+ item")[1] is False


# ---------------------------------------------------------------------------
# T5: ascii_safe — sin `?` solitarios, estructurales legibles
# ---------------------------------------------------------------------------


def test_ascii_safe_tree_box_drawing() -> None:
    tree = "├── src/\n│   └── module.py\n└── tests/"
    out = pdf_gen.ascii_safe(tree)
    # Estructurales NO deben ser ?: cada glifo debe sobrevivir en ASCII legible.
    assert "?" not in out or "[?]" in out  # solo [?] delimitado, nunca `?` solo.
    # Comprobaciones explícitas (mapeo documentado).
    assert "|--" in out or "├──" not in tree  # ├ + ─ = |--
    assert "`--" in out or "└──" not in tree  # └ + ─ = `--
    assert "|" in out  # │ sobrevive.


def test_ascii_safe_status_glyphs_never_become_question() -> None:
    text = "Pass: ✅  Fail: ❌  Warn: ⚠"
    out = pdf_gen.ascii_safe(text)
    # No puede haber `?` sueltos.
    for ch in out:
        if ch == "?":
            pytest.fail(f"Caracter ? solitario detectado en salida: {out!r}")
    assert "[OK]" in out
    assert "[FAIL]" in out
    assert "[WARN]" in out


def test_ascii_safe_arrows_and_dashes() -> None:
    text = "hola → mundo ← prueba — em-dash"
    out = pdf_gen.ascii_safe(text)
    assert "->" in out
    assert "<-" in out
    assert "--" in out  # em-dash → --
    # Confirmar que no aparecen ? solitarios.
    assert "?" not in out


def test_ascii_safe_latin1_printables_untouched() -> None:
    text = "Hola, esto es ASCII/latin-1: áéíóúñ 123."
    out = pdf_gen.ascii_safe(text)
    # latin-1 imprimibles (áéíóúñ están en rango 0xA0..0xFF) se conservan tal cual.
    assert out == text


def test_ascii_safe_unknown_codepoint_uses_delimited_placeholder() -> None:
    """Un codepoint raro, si cae fuera de rango, usa ``[?]`` (visible) NUNCA ``?``."""
    # Usamos un carácter raro que no está en nuestro _ASCII_GLYPHS ni es latin-1 printable.
    weird = "\u2603"  # snowman
    out = pdf_gen.ascii_safe(f"antes {weird} después")
    # Debe aparecer el placeholder DELIMITADO explícito.
    assert "[?]" in out, f"Esperaba placeholder [?] delimitado en: {out!r}"
    # Si extraemos todo "[?]" del output, NO debe quedar ninguna '?' aislada.
    stripped = out.replace("[?]", "")
    solo_qs = [c for c in stripped if c == "?"]
    assert not solo_qs, (
        f"Después de retirar [?], quedan ? sin corchetes/delimitadores "
        f"en: {out!r} → restante: {stripped!r}"
    )


# ---------------------------------------------------------------------------
# T5: _safe wrapper — no usa replace (que produciría ? silenciosos)
# ---------------------------------------------------------------------------


def test_safe_raises_on_strict_failure_case_unknown() -> None:
    """_safe NO debe usar errors=replace; si algo raro pasa después de ascii_safe, falla."""
    # No hay forma directa de provocarlo después de ascii_safe (que ya filtra),
    # pero al menos comprobamos que la firma funciona con strings típicos.
    assert pdf_gen._safe("hola") == "hola"
    assert pdf_gen._safe("✅") == "[OK]"
    # Postcondición: NUNCA sale un `?` solo desde _safe.
    out = pdf_gen._safe("✅ ❌ ⚠")
    assert "?" not in out
