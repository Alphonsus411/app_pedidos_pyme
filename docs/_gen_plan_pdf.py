"""
Generador de PDF compatible con fpdf2 v1.7.x (API clásica).
Plan Entrega 0.1: Architectural Baseline
"""
from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

from fpdf import FPDF

MD_PATH = Path(__file__).parent / "plan_entrega_0.1_architectural_baseline.md"
PDF_PATH = Path(__file__).parent / "plan_entrega_0.1_architectural_baseline.pdf"


# ----------------------------------------------------------------
# AYUDA UTF-8: fpdf v1.x no maneja Unicode nativo; usamos
# latin-1 con replace para evitar errores (caracteres más comunes)
# ----------------------------------------------------------------
def _safe(text: str) -> str:
    """Convierte texto a latin-1 con sustitución de caracteres no imprimibles."""
    if text is None:
        return ""
    # Sustituciones comunes antes del encoding fallback
    replacements = {
        "—": "-",  "–": "-",  "…": "...",
        "“": '"',  "”": '"',  "‘": "'",  "’": "'",
        "«": "<<", "»": ">>",
        "•": "*",  "·": "-",
        "→": "->", "←": "<-", "↔": "<->", "⇒": "=>",
        "≈": "~=", "≠": "!=", "≤": "<=", "≥": ">=",
        "±": "+-", "×": "x",  "÷": "/",
        "√": "sqrt", "∞": "inf",
        "α": "alpha", "β": "beta", "γ": "gamma",
        "δ": "delta", "π": "pi",   "Ω": "Omega",
        "©": "(C)", "®": "(R)", "™": "(TM)",
        "←": "<-",
    }
    s = text
    for old, new in replacements.items():
        s = s.replace(old, new)
    # Por último, encode a latin-1 con errores reemplazados por '?'
    return s.encode("latin-1", errors="replace").decode("latin-1")


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
    def add_list_items(self, items: list[tuple[int, bool, str]]) -> None:
        counters: dict[int, int] = {}
        for depth, ordered, text in items:
            c = counters.get(depth, 0) + 1 if ordered else 1
            counters[depth] = c if ordered else 1
            for k in list(counters.keys()):
                if k > depth:
                    del counters[k]
            self._write_list_item(depth, ordered, c, text)
        self.ln(1)

    def _write_list_item(self, depth: int, ordered: bool, num: int, text: str) -> None:
        indent = depth * 6
        bullet = f"{num}. " if ordered else "- "
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        t = re.sub(r"`(.+?)`", r"[\1]", t)
        t = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", t)

        x0 = 10 + indent
        y0 = self.get_y()
        if y0 > 270:
            self.add_page()
            y0 = self.get_y()

        # Bullet
        self.set_xy(x0, y0)
        self.set_font("Helvetica", "B", 10)
        self.cell(5 + depth, 5.5, _safe(bullet))

        # Texto multi_cell
        remaining_w = 210 - x0 - 6 - 10
        self.set_font("Helvetica", "", 10)
        self.set_text_color(30, 30, 30)
        self.set_xy(x0 + 5 + depth, y0)
        self.multi_cell(remaining_w, 5.5, _safe(t))

    # ---------- Código ----------
    def add_code_block(self, lines: list[str]) -> None:
        self.ln(2)
        prev_font = (self.font_family, self.font_style_pt, self.font_size_pt) \
            if hasattr(self, "font_style_pt") else ("Helvetica", "", 10)
        prev_text = self.text_color

        self.set_code()
        block = lines if lines else [""]
        line_h = 4.8
        total_h = len(block) * line_h + 4
        y = self.get_y()
        if y + total_h > 275:
            self.add_page()
            y = self.get_y()

        # Fondo gris
        x = 10
        self.rect(x, y, 190, total_h, style="F")
        self.set_xy(x + 3, y + 2)

        for ln in block:
            ln_e = ln.replace("\t", "    ")
            wrapped = textwrap.wrap(ln_e, width=100,
                                    break_long_words=True,
                                    break_on_hyphens=False) or [""]
            for wl in wrapped:
                self.set_x(x + 3)
                self.cell(0, line_h, _safe(wl), border=0, ln=1)
        self.ln(3)
        self.set_body()
        _ = prev_font, prev_text  # no restauramos fuentes v1.x (set_body ya lo hace)

    # ---------- Tabla ----------
    def add_table(self, header_line: str, separator_line: str, body_lines: list[str]) -> None:
        def split_row(row: str) -> list[str]:
            s = row.strip()
            if s.startswith("|"):
                s = s[1:]
            if s.endswith("|"):
                s = s[:-1]
            return [c.strip() for c in s.split("|")]

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
        m_ord = re.match(r"^(\s*)(\d+)\.\s+(.+)$", stripped)
        m_un = re.match(r"^(\s*)([-*+])\s+(.+)$", stripped)

        def collect_list() -> list[tuple[int, bool, str]]:
            nonlocal i
            items: list[tuple[int, bool, str]] = []
            while i < n:
                ln = lines[i].rstrip()
                if not ln.strip():
                    # Mirar siguiente línea para listas continuadas
                    if i + 1 < n and (re.match(r"^(\s*)(\d+)\.\s+", lines[i + 1])
                                      or re.match(r"^(\s*)([-*+])\s+", lines[i + 1])):
                        i += 1
                        continue
                    break
                mo = re.match(r"^(\s*)(\d+)\.\s+(.+)$", ln)
                mu = re.match(r"^(\s*)([-*+])\s+(.+)$", ln)
                if mo:
                    depth = len(mo.group(1)) // 2
                    items.append((depth, True, mo.group(3)))
                    i += 1
                elif mu:
                    depth = len(mu.group(1)) // 2
                    items.append((depth, False, mu.group(3)))
                    i += 1
                else:
                    break
            return items

        if m_ord or m_un:
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
                or re.match(r"^(\s*)(\d+)\.\s+", nxt)
                or re.match(r"^(\s*)([-*+])\s+", nxt)
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
