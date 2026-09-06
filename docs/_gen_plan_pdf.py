"""
Generador PDF para `docs/plan_entrega_0.1_architectural_baseline.md` → .pdf.

Requiere extra opcional (NO dependencia runtime del Universal Business Core):
    pip install -e ".[docs]"      # incluye fpdf2
    python docs/_gen_plan_pdf.py

Plan Entrega 0.1: Architectural Baseline — v2.1 (Gate 0.1 Final Audit).
Usa API fpdf v1.x (Helvetica con sustituciones ASCII seguras; NO Unicode nativo).
Las funciones de ayuda (`split_table_row`, list marker preservation, code
pagination, ASCII fallback tree) son pure-Python y se validan por tests unitarios
dedicados en `tests/unit/test_docs_pdf_generator.py`.
"""
from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path
from typing import Iterable

from fpdf import FPDF

MD_PATH = Path(__file__).parent / "plan_entrega_0.1_architectural_baseline.md"
PDF_PATH = Path(__file__).parent / "plan_entrega_0.1_architectural_baseline.pdf"


# =================================================================
# Helpers públicos (pure, sin FPDF ni estado) — testables sin PDF.
# =================================================================

# ---- T2: Escaped pipes en tablas --------------------------------
_PIPE_RE = re.compile(r"\\?[|]")


def split_table_row(row: str) -> list[str]:
    r"""Divide una fila de tabla Markdown por pipes NO escapados.

    - Ignora los pipes de borde extremo (inicio/fin de línea).
    - ``foo\|bar`` produce una única celda con el literal ``foo|bar``
      (el escape ``\\`` se retira solo después de segmentar).
    - Número de columnas = número de celdas reales.
    """
    s = row.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            # pipe escapado: conservar literal (sin barra invertida)
            buf.append("|")
            i += 2
        elif ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    cells.append("".join(buf).strip())
    return cells


# ---- T3: Preservar marcador fuente de listas ordenadas ---------
LIST_ORDERED_RE = re.compile(r"^(\s*)(\S+?)\.\s+(.+)$")
LIST_UNORDERED_RE = re.compile(r"^(\s*)([-*+])\s+(.+)$")


def parse_list_line(line: str) -> tuple[int, bool, str | None, str] | None:
    """Detecta una línea de lista Markdown y extrae:
    ``(depth, ordered, source_marker_or_None, content)``.

    - Listas ordenadas: ``source_marker`` es el literal antes del ``.``
      (ej. ``"4"`` para ``4.``, ``"29-40"`` para ``29-40.``).
    - Listas NO ordenadas: ``source_marker is None``.
    - Retorna ``None`` si no es una línea de lista.
    """
    mo = LIST_ORDERED_RE.match(line.rstrip())
    if mo:
        indent = len(mo.group(1).replace("\t", "  "))
        depth = indent // 2
        # Aceptamos marcadores NO puramente numéricos tipo "29-40." solo si
        # son alfanuméricos sin whitespace. Si el prefijo es NO estructural
        # (letras raras) lo tratamos igual de todas formas: el renderer
        # conservará el literal fuente y nunca inventará números nuevos.
        marker_src = mo.group(2)
        content = mo.group(3)
        return depth, True, marker_src, content
    mu = LIST_UNORDERED_RE.match(line.rstrip())
    if mu:
        indent = len(mu.group(1).replace("\t", "  "))
        depth = indent // 2
        content = mu.group(3)
        return depth, False, None, content
    return None


# ---- T5: Unicode → ASCII fallbacks seguros (sin ?) -------------
_ASCII_GLYPHS: dict[str, str] = {
    # Box-drawing / tree
    "├": "|",
    "│": "|",
    "└": "`",
    "─": "-",
    "┬": "+",
    "┴": "+",
    "┼": "+",
    "┌": ",",
    "┐": ",",
    "└": "`",
    "┘": "'",
    "╔": "+",
    "╗": "+",
    "╚": "+",
    "╝": "+",
    "═": "=",
    "║": "|",
    # Status / misc glyphs
    "✅": "[OK]",
    "✔": "[OK]",
    "☑": "[OK]",
    "✓": "[OK]",
    "❌": "[FAIL]",
    "✖": "[FAIL]",
    "✗": "[FAIL]",
    "✘": "[FAIL]",
    "⚠": "[WARN]",
    "🛑": "[STOP]",
    "🟢": "[OK]",
    "🔴": "[FAIL]",
    "🟡": "[WARN]",
    "⚪": "[ ]",
    "🟣": "[?]",
    # Pointers
    "→": "->",
    "←": "<-",
    "↔": "<->",
    "⇒": "=>",
    "⇐": "<=",
    "⇔": "<=>",
    # Guiones / comillas comunes
    "—": "--",
    "–": "-",
    "…": "...",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "«": "<<",
    "»": ">>",
    "•": "*",
    "·": "-",
    "√": "sqrt",
    "∞": "inf",
    "≈": "~=",
    "≠": "!=",
    "≤": "<=",
    "≥": ">=",
    "±": "+-",
    "×": "x",
    "÷": "/",
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "π": "pi",
    "Ω": "Omega",
    "©": "(C)",
    "®": "(R)",
    "™": "(TM)",
}
_ASCII_TRANSLATE = str.maketrans(_ASCII_GLYPHS)


def ascii_safe(text: str) -> str:
    """Convierte texto a ASCII SAFE sin caracteres ``?``.

    Reemplaza:
      - glifos de árbol box-drawing con equivalentes ASCII
        (``├──`` → ``|--``, ``└──`` → ```--``, ``│`` → ``|``).
      - símbolos de estado (``✅/❌/⚠`` → ``[OK]/[FAIL]/[WARN]``).
      - comillas, em-dash, flechas, operadores matemáticos comunes.
      - cualquier otro carácter no imprimible en latin-1 se reemplaza por
        ``[?]`` (estándar visible; nunca el silencioso ``?`` sin
        delimitadores que confundía el contenido).
    Nunca genera ``?`` sueltos.
    """
    if text is None:
        return ""
    s = text.translate(_ASCII_TRANSLATE)
    # Box-drawing composites frecuentes sin loop de retrans:
    s = s.replace("|--", "|--").replace("`--", "`--")
    # Fallback de lo que quede fuera de latin-1 imprimible a [?]
    out_chars: list[str] = []
    for ch in s:
        code = ord(ch)
        # imprimibles latin-1: 0x20..0x7E (ASCII) + 0xA0..0xFF (ISO-8859-1 printable).
        # Excluimos 0x7F (DEL) y el rango 0x80..0x9F (controles).
        is_printable_latin1 = (0x20 <= code <= 0x7E) or (0xA0 <= code <= 0xFF)
        if ch in ("\n", "\r", "\t") or is_printable_latin1:
            out_chars.append(ch)
        else:
            out_chars.append("[?]")
    return "".join(out_chars)


def _safe(text: str) -> str:
    """Wrapper PDF: convierte a ASCII seguro y después encodea latin-1
    con ``errors='strict'`` (NO se permite ``replace`` que genere ``?``)."""
    if text is None:
        return ""
    return ascii_safe(text).encode("latin-1", errors="strict").decode("latin-1")


class PlanPDF(FPDF):
    """FPDF con encabezado y pie personalizados."""

    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self.alias_nb_pages()

    # ---------- Encabezado ----------
    def header(self) -> None:
        if self.page_no() <= 1:
            return
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, _safe("Universal Business Core — Plan Entrega 0.1: Architectural Baseline"),
                  border=0, ln=0, align="L")
        self.ln(5)
        y = self.get_y()
        self.line(10, y, 200, y)
        self.ln(2)

    # ---------- Pie ----------
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, _safe(f"Pagina {self.page_no()}/{{nb}}"),
                  border=0, ln=0, align="C")

    # ---------- Helpers tipográficos ----------
    def set_heading(self, level: int) -> None:
        sizes = {1: 22, 2: 17, 3: 14, 4: 12, 5: 11, 6: 10}
        size = sizes.get(level, 10)
        colors = {
            1: (25, 55, 110),
            2: (35, 75, 135),
            3: (55, 95, 155),
            4: (75, 115, 175),
        }
        r, g, b = colors.get(level, (75, 75, 75))
        self.set_font("Helvetica", "B", size)
        self.set_text_color(r, g, b)

    def set_body(self, style: str = "") -> None:
        self.set_font("Helvetica", style, 10)
        self.set_text_color(30, 30, 30)

    def set_code(self) -> None:
        self.set_font("Courier", "", 8.5)
        self.set_text_color(40, 40, 40)
        self.set_fill_color(245, 245, 245)

    # ---------- Página título ----------
    def add_title_page(self) -> None:
        self.add_page()
        self.ln(30)
        self.set_font("Helvetica", "B", 26)
        self.set_text_color(25, 55, 110)
        self.cell(0, 15, _safe("PLAN DE IMPLEMENTACION"), border=0, ln=1, align="C")
        self.cell(0, 12, _safe("Entrega 0.1 - Architectural Baseline"),
                  border=0, ln=1, align="C")
        self.ln(8)
        self.set_draw_color(25, 55, 110)
        self.line(30, self.get_y(), 180, self.get_y())
        self.ln(10)
        self.set_font("Helvetica", "", 12)
        self.set_text_color(60, 60, 60)
        lines = [
            "Documento: Plan detallado de implementacion",
            "Version: 1.0",
            "Fecha: 5 de septiembre de 2026",
            "Branch: feat/architectural-baseline",
            "Referencia: hoja_ruta_universal_business_core.pdf",
        ]
        for ln in lines:
            self.cell(0, 9, _safe(ln), border=0, ln=1, align="C")
        self.ln(35)
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 7, _safe("Universal Business Core - Monolito modular, dominio agnostico, multi-tenant"),
                  border=0, ln=1, align="C")
        self.cell(0, 7, _safe("Espera aprobacion antes de proceder a la implementacion."),
                  border=0, ln=1, align="C")

    # ---------- Encabezado estructural ----------
    def add_heading(self, text: str, level: int) -> None:
        before = {1: 8, 2: 6, 3: 4, 4: 3, 5: 2, 6: 2}.get(level, 2)
        after = {1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 2}.get(level, 2)
        self.ln(before)
        if self.get_y() > 250:
            self.add_page()
        self.set_heading(level)
        h = 7 + level * 0.3
        self.multi_cell(0, h, _safe(text))
        self.ln(after)

    # ---------- Párrafo ----------
    def add_paragraph(self, text: str) -> None:
        self.set_body()
        if not text.strip():
            self.ln(2)
            return
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        t = re.sub(r"`(.+?)`", r"[\1]", t)
        t = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", t)
        self.multi_cell(0, 5.5, _safe(t))
        self.ln(1.5)

    # ---------- Lista ----------
    def add_list_items(self, items: list[tuple[int, bool, str | None, str]]) -> None:
        """Renderiza lista conservando el marcador fuente cuando está disponible.

        Cada ítem: ``(depth, ordered, source_marker, content)``.

        - Si ``ordered=True`` y ``source_marker`` es str NO vacío → lo usamos
          literalmente (ej. ``"4"`` → ``"4. "``, ``"29-40"`` → ``"29-40. "``).
        - Si ``ordered=True`` pero ``source_marker in (None, "")`` → mantenemos
          un contador *per-depth* como fallback (Markdown realmente no trae
          marcador explícito → comportamiento seguro, no inventamos para
          listas que sí lo traían).
        - Listas no ordenadas siempre ``"- "``.
        """
        counters: dict[int, int] = {}
        for item in items:
            depth, ordered, src_marker, text = item
            if ordered:
                if src_marker:
                    bullet = f"{src_marker}. "
                else:
                    c = counters.get(depth, 0) + 1
                    counters[depth] = c
                    bullet = f"{c}. "
            else:
                bullet = "- "
                counters[depth] = 1
            # Resetear contadores de profundidades mayores al actual (reset sublist)
            for k in list(counters.keys()):
                if k > depth:
                    del counters[k]
            self._write_list_item(depth, ordered, bullet, text)
        self.ln(1)

    def _write_list_item(self, depth: int, ordered: bool, bullet: str, text: str) -> None:
        _ = ordered  # bullet ya lleva toda la información necesaria
        indent = depth * 6
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        t = re.sub(r"`(.+?)`", r"[\1]", t)
        t = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", t)

        x0 = 10 + indent
        y0 = self.get_y()
        if y0 > 270:
            self.add_page()
            y0 = self.get_y()

        # Bullet (negrita para distinguir)
        self.set_xy(x0, y0)
        self.set_font("Helvetica", "B", 10)
        self.cell(max(5 + depth, len(bullet) * 2.1), 5.5, _safe(bullet))

        # Texto multi_cell
        bullet_w = max(5 + depth, len(bullet) * 2.1)
        remaining_w = 210 - x0 - bullet_w - 10
        self.set_font("Helvetica", "", 10)
        self.set_text_color(30, 30, 30)
        self.set_xy(x0 + bullet_w, y0)
        self.multi_cell(remaining_w, 5.5, _safe(t))

    # ---------- Código (con paginación por fragmentos) ----------
    def add_code_block(self, lines: list[str]) -> None:
        """Renderiza un bloque de código paginando correctamente.

        - Si el bloque NO cabe en la página actual, parte el bloque por líneas.
        - Cada página dibuja SU PROPIO fondo gris (rectángulo) para las líneas
          que efectivamente imprime en esa página.
        - Nunca dibuja un rectángulo mayor que el alto disponible.
        - Reutiliza: line_h, set_code (tipografía, fill_color), márgenes.
        - No corta texto ilegiblemente: partimos por línea entera.
        """
        self.ln(2)
        self.set_code()
        block = lines if lines else [""]
        line_h = 4.8
        pad_top = 2
        pad_bottom = 2
        x = 10
        w = 190
        top_margin_after_header = 10  # header por defecto ya respeta ~10mm
        bottom_safe = 275
        remaining: list[str] = list(block)
        while remaining:
            # Líneas que caben en la página actual
            y = self.get_y()
            if y > 270:
                self.add_page()
                y = self.get_y()
            available_h = bottom_safe - y
            # Alto total que queremos ocupar = lines_per_page * line_h + pad_top + pad_bottom
            # → lines_per_page = floor((available_h - pad_top - pad_bottom) / line_h)
            lines_per_page = int((available_h - pad_top - pad_bottom) // line_h)
            if lines_per_page <= 0:
                lines_per_page = 1
            chunk = remaining[:lines_per_page]
            remaining = remaining[lines_per_page:]

            # Fondo gris para el chunk actual
            chunk_h = len(chunk) * line_h + pad_top + pad_bottom
            self.rect(x, y, w, chunk_h, style="F")
            self.set_xy(x + 3, y + pad_top)

            for ln in chunk:
                ln_e = ln.replace("\t", "    ")
                wrapped = textwrap.wrap(
                    ln_e,
                    width=100,
                    break_long_words=True,
                    break_on_hyphens=False,
                ) or [""]
                for wl in wrapped:
                    self.set_x(x + 3)
                    self.cell(0, line_h, _safe(wl), border=0, ln=1)

            # Salto de página si quedan líneas pendientes
            if remaining:
                self.add_page()

        self.ln(3)
        self.set_body()

    # ---------- Tabla ----------
    def add_table(self, header_line: str, separator_line: str, body_lines: list[str]) -> None:
        def split_row(row: str) -> list[str]:
            # T2: delega al helper robusto que respeta pipes escapados `\|`
            return split_table_row(row)

        headers = split_row(header_line)
        _ = separator_line
        rows = [split_row(r) for r in body_lines if r.strip() and r.strip().startswith("|")]

        num_cols = max(len(headers), max((len(r) for r in rows), default=0))
        while len(headers) < num_cols:
            headers.append("")
        for r in rows:
            while len(r) < num_cols:
                r.append("")

        margin_total = 20
        available = 190 - margin_total
        col_w = available / num_cols

        self.ln(3)
        if self.get_y() + (len(rows) + 1) * 12 > 270:
            self.add_page()

        # Altura fila según contenido
        def calc_row_height(cells: list[str], bold: bool = False) -> float:
            self.set_font("Helvetica", "B" if bold else "", 9)
            max_h = 6.0
            chars_per_line = max(1, int(col_w / 2.1))
            for c in cells:
                clean = re.sub(r"\*\*(.+?)\*\*", r"\1", c)
                clean = re.sub(r"`(.+?)`", r"[\1]", clean)
                if not clean:
                    n = 1
                else:
                    # Aproximar líneas por texto largo; multi_cell lo decide solo
                    n = max(1, (len(clean) // chars_per_line) + clean.count("\n") + 1)
                    # Si hay chars muy largos, textwrap lo parte -> líneas más
                    wrapped = textwrap.wrap(clean, width=chars_per_line,
                                            break_long_words=True)
                    n = max(n, len(wrapped) if wrapped else 1)
                max_h = max(max_h, n * 5.0 + 2)
            return max_h

        # Encabezado
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(25, 55, 110)
        self.set_text_color(255, 255, 255)
        h_h = calc_row_height(headers, bold=True)
        y = self.get_y()
        x0 = 10
        x = x0
        for cell in headers:
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", cell)
            clean = re.sub(r"`(.+?)`", r"[\1]", clean)
            # Fondo
            self.set_xy(x, y)
            self.rect(x, y, col_w, h_h, style="F")
            self.set_xy(x + 1, y + 1)
            # multi_cell escribe con borde a veces; mejor solo texto
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(255, 255, 255)
            # Escribir texto multilínea manualmente con multi_cell
            # En v1.x multi_cell avanza ln=1 por defecto -> reseteamos x
            self.multi_cell(col_w - 2, 5, _safe(clean), border=0, align="L")
            x += col_w
        # Asegurar que la y queda al final de la fila
        self.set_xy(x0, y + h_h)

        # Filas
        self.set_font("Helvetica", "", 9)
        self.set_text_color(30, 30, 30)
        zebra = True
        for row in rows:
            zebra = not zebra
            if zebra:
                self.set_fill_color(240, 244, 250)
            else:
                self.set_fill_color(255, 255, 255)
            h_r = calc_row_height(row, bold=False)
            y = self.get_y()
            if y + h_r > 275:
                self.add_page()
                y = self.get_y()
            x = x0
            for cell in row:
                clean = re.sub(r"\*\*(.+?)\*\*", r"\1", cell)
                clean = re.sub(r"`(.+?)`", r"[\1]", clean)
                clean = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", clean)
                # Fondo
                self.rect(x, y, col_w, h_r, style="F")
                self.set_xy(x + 1, y + 1)
                self.set_font("Helvetica", "", 9)
                self.set_text_color(30, 30, 30)
                self.multi_cell(col_w - 2, 5, _safe(clean), border=0, align="L")
                x += col_w
            self.set_xy(x0, y + h_r)

        # Línea inferior
        self.set_draw_color(200, 200, 200)
        self.line(x0, self.get_y(), 200, self.get_y())
        self.ln(5)
        self.set_body()

    # ---------- HR ----------
    def add_hr(self) -> None:
        self.ln(2)
        self.set_draw_color(180, 180, 180)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(3)


# ================================================================
# Parser markdown suficiente para este documento
# ================================================================
def parse_and_render(md_text: str, pdf: PlanPDF) -> None:
    lines = md_text.splitlines()
    i = 0
    n = len(lines)

    first_h1_found = False

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        # --- Código ``` ---
        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < n and not lines[i].rstrip().startswith("```"):
                code_lines.append(lines[i].rstrip())
                i += 1
            i += 1
            pdf.add_code_block(code_lines)
            continue

        # --- Tabla ---
        if (i + 1 < n and "|" in stripped and stripped.strip().startswith("|")
                and re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$", lines[i + 1])):
            header = stripped
            sep = lines[i + 1]
            body: list[str] = []
            i += 2
            while i < n and lines[i].strip().startswith("|"):
                body.append(lines[i].rstrip())
                i += 1
            pdf.add_table(header, sep, body)
            continue

        # --- Headings ---
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            txt = m.group(2).strip()
            if level == 1 and not first_h1_found:
                first_h1_found = True
                i += 1
                continue
            pdf.add_heading(txt, level)
            i += 1
            continue

        # --- Vacía ---
        if not stripped.strip():
            i += 1
            continue

        # --- HR ---
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", stripped):
            pdf.add_hr()
            i += 1
            continue

        # --- Listas ---
        # T3: usamos el helper común que captura el marcador fuente literal
        #     (p. ej. "4", "29-40") para listas ordenadas; el renderer NO inventa números.
        parsed_head = parse_list_line(stripped)

        def _peek_is_list(idx: int) -> bool:
            if idx >= n:
                return False
            return parse_list_line(lines[idx].rstrip()) is not None

        def collect_list() -> list[tuple[int, bool, str | None, str]]:
            nonlocal i
            items: list[tuple[int, bool, str | None, str]] = []
            while i < n:
                ln = lines[i].rstrip()
                if not ln.strip():
                    # Mirar siguiente línea para listas continuadas (separador
                    # de un solo blank line).
                    if i + 1 < n and _peek_is_list(i + 1):
                        i += 1
                        continue
                    break
                parsed = parse_list_line(ln)
                if parsed is not None:
                    depth, ordered, src_marker, content = parsed
                    items.append((depth, ordered, src_marker, content))
                    i += 1
                else:
                    break
            return items

        if parsed_head is not None:
            items = collect_list()
            pdf.add_list_items(items)
            continue

        # --- Párrafo (acumula líneas continuas) ---
        buf: list[str] = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].rstrip()
            if not nxt.strip():
                break
            if (re.match(r"^(#{1,6})\s+", nxt)
                or parse_list_line(nxt) is not None
                or nxt.strip().startswith("```")
                or (nxt.strip().startswith("|") and i + 1 < n
                    and re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$", lines[i + 1]))
                or re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", nxt)):
                break
            buf.append(nxt)
            i += 1
        paragraph = " ".join(b.strip() for b in buf)
        pdf.add_paragraph(paragraph)


def main() -> int:
    md_text = MD_PATH.read_text(encoding="utf-8")

    pdf = PlanPDF()
    pdf.add_title_page()
    parse_and_render(md_text, pdf)
    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(PDF_PATH), dest="F")
    size = PDF_PATH.stat().st_size
    print(f"OK  PDF generado: {PDF_PATH}  ({size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
