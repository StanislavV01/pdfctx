"""Deterministic test PDFs built with reportlab.

Every fact the tests assert on (headings, sentences, table cells, pages) is defined here.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONTS = Path(__file__).parent / "data" / "fonts"
W, H = letter
MARGIN = 72
FILLER = (
    "This section describes the operations of the company during the fiscal year. "
    "Management reviewed the performance of each business unit and the outlook for the next period."
)

REPORT_TITLE = "ACME Annual Report 2025"
HEADINGS = ["1 Introduction", "1.1 Scope", "2 Results", "2.1 Revenue", "3 Risks"]
REVENUE_SENTENCE = "Revenue grew 12% year over year."
TERMINATION_SENTENCE = "The termination notice period is ninety days."
TABLE_LEAD_IN = "Revenue by region (in thousands):"
TABLE = [
    ["Region", "2025", "2024"],
    ["North", "1,200", "1,050"],
    ["South", "800", "760"],
    ["Total", "2,000", "1,810"],
]


def _wrap(c: canvas.Canvas, text: str, font: str, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if c.stringWidth(trial, font, size) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


class _Writer:
    def __init__(self, path: Path, *, bookmarks: bool, running: bool = True):
        self.c = canvas.Canvas(str(path), pagesize=letter)
        self.c.setTitle("")
        self.bookmarks = bookmarks
        self.running = running
        self.page = 1
        self.y = H - MARGIN - 20
        self._chrome()

    def _chrome(self) -> None:
        if not self.running:
            return
        self.c.setFont("Helvetica", 8)
        self.c.drawString(MARGIN, H - 40, "ACME Annual Report")
        self.c.drawString(W / 2 - 15, 30, f"Page {self.page}")

    def new_page(self) -> None:
        self.c.showPage()
        self.page += 1
        self.y = H - MARGIN - 20
        self._chrome()

    def heading(self, text: str, size: float, level: int) -> None:
        self.y -= size * 0.8
        key = f"h{self.page}_{int(self.y)}"
        self.c.bookmarkPage(key, fit="XYZ", top=self.y + size)
        if self.bookmarks:
            self.c.addOutlineEntry(text, key, level=level - 1)
        self.c.setFont("Helvetica-Bold", size)
        self.c.drawString(MARGIN, self.y, text)
        self.y -= size * 1.2

    def para(self, text: str, size: float = 10, font: str = "Helvetica") -> None:
        for line in _wrap(self.c, text, font, size, W - 2 * MARGIN):
            self.c.setFont(font, size)
            self.c.drawString(MARGIN, self.y, line)
            self.y -= size * 1.35
        self.y -= size * 0.9

    def table(self, rows: list[list[str]], col_w: float = 110, row_h: float = 18) -> None:
        x0, top = MARGIN, self.y
        for r, row in enumerate(rows):
            for col, cell in enumerate(row):
                x = x0 + col * col_w
                y = top - (r + 1) * row_h
                self.c.rect(x, y, col_w, row_h)
                self.c.setFont("Helvetica-Bold" if r == 0 else "Helvetica", 9)
                self.c.drawString(x + 4, y + 5, cell)
        self.y = top - len(rows) * row_h - 20

    def save(self) -> None:
        self.c.save()


def make_report(path: Path, bookmarks: bool = True) -> Path:
    w = _Writer(path, bookmarks=bookmarks)
    w.c.setFont("Helvetica-Bold", 20)
    w.c.drawString(MARGIN, w.y, REPORT_TITLE)
    w.y -= 40
    w.heading("1 Introduction", 14, 1)
    w.para(FILLER)
    w.para("ACME builds industrial pumps and sells them in two regions. " + FILLER)
    w.heading("1.1 Scope", 12, 2)
    w.para("This report covers the fiscal year ending December 31, 2025. " + FILLER)
    w.new_page()
    w.heading("2 Results", 14, 1)
    w.para(FILLER)
    w.heading("2.1 Revenue", 12, 2)
    w.para(f"{REVENUE_SENTENCE} Growth came mostly from the North region. " + FILLER)
    w.new_page()
    w.para("The table below shows revenue for each sales region. " + FILLER)
    w.para(TABLE_LEAD_IN)
    w.y += 8
    w.table(TABLE)
    w.para("Totals include intercompany eliminations. " + FILLER)
    w.new_page()
    w.heading("3 Risks", 14, 1)
    w.para("Our largest customer contract renews annually. " + TERMINATION_SENTENCE + " " + FILLER)
    w.para(FILLER)
    w.save()
    return path


LEFT = ["Left column first paragraph about pumps.", "Left column second paragraph about valves."]
RIGHT = ["Right column first paragraph about pipes.", "Right column second paragraph about seals."]


def make_two_column(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=letter)
    col_w = (W - 2 * MARGIN - 40) / 2
    for x, paras in ((MARGIN, LEFT), (MARGIN + col_w + 40, RIGHT)):
        y = H - MARGIN
        for p in paras:
            for line in _wrap(c, p + " " + FILLER, "Helvetica", 10, col_w):
                c.setFont("Helvetica", 10)
                c.drawString(x, y, line)
                y -= 13.5
            y -= 12
    c.save()
    return path


POLISH = "Zażółć gęślą jaźń. Договір оренди укладено на три роки."


def make_polish(path: Path) -> Path:
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONTS / "DejaVuSans.ttf")))
    c = canvas.Canvas(str(path), pagesize=letter)
    y = H - MARGIN
    for line in _wrap(c, POLISH + " " + POLISH, "DejaVu", 11, W - 2 * MARGIN):
        c.setFont("DejaVu", 11)
        c.drawString(MARGIN, y, line)
        y -= 15
    c.save()
    return path


def make_image_only(path: Path) -> Path:
    from PIL import Image

    img = Image.new("RGB", (200, 100), (200, 30, 30))
    png = path.with_suffix(".png")
    img.save(png)
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(str(png), MARGIN, H / 2, width=200, height=100)
    c.save()
    png.unlink()
    return path


def make_encrypted(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=letter, encrypt="secret")
    c.setFont("Helvetica", 12)
    c.drawString(MARGIN, H - MARGIN, "Confidential numbers live here.")
    c.save()
    return path


def make_text_report(path: Path, sentence: str) -> Path:
    """A one-page document whose only fact is `sentence` (used for re-index tests)."""
    w = _Writer(path, bookmarks=False, running=False)
    w.heading("Notes", 14, 1)
    w.para(sentence + " " + FILLER)
    w.save()
    return path
