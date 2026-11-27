"""Table detection from text alignment.

SEC filings and most HTML-to-PDF documents draw tables without ruling lines, so tables are found the
way a reader finds them: consecutive lines whose words split into a label plus right-aligned
numeric cells, with a header row of years or column names above.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Line, Word

_NUM = re.compile(r"^[(\-–—]?[$€£]?\(?-?\d[\d,]*(\.\d+)?%?\)?[)%]?$")
_DASH = {"-", "–", "—", "−", "$—", "$-", "$–"}
_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


@dataclass
class Cell:
    text: str
    x0: float
    x1: float


@dataclass
class TableRegion:
    page: int
    line_idx: list[int]  # indices (into the page's lines) owned by the table, incl. header lines
    header: list[str]
    rows: list[list[str]]
    caption: str = ""
    lead_in: str = ""
    lines: list[Line] = field(default_factory=list)


def is_number(text: str) -> bool:
    t = text.replace(" ", "")
    return t in _DASH or bool(_NUM.match(t))


def cells(line: Line) -> list[Cell]:
    """Split a line into cells at gaps wider than ~1.5 em; glue lone currency/percent signs."""
    out: list[Cell] = []
    prev: Word | None = None
    for w in line.words:
        gap_limit = max(1.5 * w.size, 6.0)
        currency = w.text in {"$", "€", "£"}
        if (
            out
            and prev is not None
            and not currency
            and out[-1].text not in {"$", "€", "£"}
            and w.x0 - prev.x1 <= gap_limit
        ):
            c = out[-1]
            c.text, c.x1 = f"{c.text} {w.text}", w.x1
        else:
            out.append(Cell(w.text, w.x0, w.x1))
        prev = w
    merged: list[Cell] = []
    for c in out:
        if merged and merged[-1].text in {"$", "€", "£"}:
            last = merged.pop()
            c = Cell(f"{last.text}{c.text}", last.x0, c.x1)
        elif merged and c.text in {"%", ")"}:
            merged[-1].text += c.text
            merged[-1].x1 = c.x1
            continue
        merged.append(c)
    return merged


def _kind(cs: list[Cell], line: Line) -> str:
    """T = table row, Y = header row (years / column names), L = short label line, O = other."""
    values = cs[1:] if cs and not is_number(cs[0].text) else cs
    numeric = [c for c in values if is_number(c.text)]
    if len(cs) >= 2 and values and all(_YEAR.search(c.text) for c in values) and len(values) >= 2:
        return "Y"
    if len(cs) >= 2 and numeric and len(numeric) >= len(values) - 1:
        return "T"
    words = line.text.split()
    if len(cs) == 1 and len(words) <= 20 and not line.text.rstrip().endswith((".", ":")):
        return "L"
    if len(cs) >= 3 and not numeric and len(words) <= 12:
        return "H"  # text column headers
    return "O"


def _columns(rows: list[list[Cell]]) -> list[float]:
    """Right edges of value columns, clustered across rows."""
    edges = sorted(c.x1 for cs in rows for c in (cs[1:] if not is_number(cs[0].text) else cs))
    cols: list[list[float]] = []
    for e in edges:
        if cols and e - cols[-1][-1] <= 12:
            cols[-1].append(e)
        else:
            cols.append([e])
    return [sum(c) / len(c) for c in cols if len(c) >= max(1, len(rows) // 4)]


def _place(values: list[Cell], cols: list[float]) -> list[str]:
    out = [""] * len(cols)
    for c in values:
        best = min(range(len(cols)), key=lambda k: abs(cols[k] - c.x1)) if cols else 0
        if not cols:
            continue
        while best < len(cols) and out[best]:
            best += 1
        if best < len(cols):
            out[best] = c.text
    return out


def find_tables(lines: list[Line]) -> list[TableRegion]:
    """Tables on one page. `lines` must be the page's lines in reading order."""
    parsed = [cells(ln) for ln in lines]
    kinds = [_kind(cs, ln) for cs, ln in zip(parsed, lines, strict=True)]
    regions: list[TableRegion] = []
    i = 0
    while i < len(lines):
        if kinds[i] not in "TY":
            i += 1
            continue
        start, j, t_rows = i, i, 0
        last_t = -1
        while j < len(lines) and kinds[j] in "TYL":
            if kinds[j] == "T":
                t_rows += 1
                last_t = j
            elif kinds[j] == "L" and j - max(last_t, start) > 2:
                break
            j += 1
        if t_rows < 2 or last_t < 0:
            i = max(j, i + 1)
            continue
        end = last_t  # inclusive; trailing label lines are not part of the table
        idx = list(range(start, end + 1))
        # Header and caption lines directly above the table.
        above: list[int] = []
        k = start - 1
        while k >= 0 and len(above) < 3 and kinds[k] in "YHL":
            gap = lines[k + 1].top - lines[k].bottom
            if gap > 3 * lines[k].size:
                break
            above.insert(0, k)
            k -= 1
        header_lines = [k for k in above + idx if kinds[k] in "YH"]
        header_lines = [k for k in header_lines if k < (min(x for x in idx if kinds[x] == "T"))]
        caption_lines = [k for k in above if k not in header_lines]

        body = [k for k in idx if k not in header_lines]
        t_cells = [parsed[k] for k in body if kinds[k] == "T"]
        cols = _columns(t_cells)
        if not cols:
            i = end + 1
            continue
        header = [""] * len(cols)
        for k in header_lines:
            cs = parsed[k]
            vals = cs[1:] if kinds[k] == "Y" and not _YEAR.search(cs[0].text) else cs
            if kinds[k] == "H":
                vals = cs[1:] if len(cs) == len(cols) + 1 else cs[-len(cols) :]
            for n, text in enumerate(_place(vals, cols)):
                if text:
                    header[n] = f"{header[n]} {text}".strip()
        rows: list[list[str]] = []
        for k in body:
            cs = parsed[k]
            if kinds[k] == "T":
                label = "" if is_number(cs[0].text) else cs[0].text
                values = cs if not label else cs[1:]
                rows.append([label, *_place(values, cols)])
            else:
                rows.append([lines[k].text, *([""] * len(cols))])
        lead_in = ""
        first = (above or idx)[0]
        if first > 0 and kinds[first - 1] == "O":
            gap = lines[first].top - lines[first - 1].bottom
            if gap <= 30:
                lead_in = lines[first - 1].text
        caption = " · ".join(lines[k].text for k in caption_lines)
        for k in header_lines:
            if kinds[k] == "Y" and not _YEAR.search(parsed[k][0].text):
                caption = f"{caption} · {parsed[k][0].text}".strip(" ·")
        owned = sorted(set(above + idx) - set(caption_lines)) + caption_lines
        regions.append(
            TableRegion(
                page=lines[start].page,
                line_idx=sorted(owned),
                header=header,
                rows=rows,
                caption=caption,
                lead_in=lead_in,
                lines=[lines[k] for k in sorted(owned)],
            )
        )
        i = end + 1
    return regions


def to_markdown(header: list[str], rows: list[list[str]], label: str = "") -> str:
    def esc(s: str) -> str:
        return s.replace("|", "\\|")

    out = ["| " + " | ".join([esc(label), *map(esc, header)]) + " |", "|" + " --- |" * (len(header) + 1)]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out)
