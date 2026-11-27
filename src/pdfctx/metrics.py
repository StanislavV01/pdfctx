"""Financial metrics from tables, every value with its source row.

Deterministic: no model reads the numbers. For each metric, rows whose label matches one of the metric's
names are read by year column; the best row per (document, metric, year) wins. Every value keeps its page,
box, label and the raw cell text, and a value that is not found stays missing. pdfctx never guesses.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass

from .errors import PdfctxError
from .store import BlockRow, Store

# Canonical metric → label prefixes as they appear in filings (lowercase, punctuation normalised).
METRICS: dict[str, list[str]] = {
    "revenue": [
        "total revenues",
        "total revenue",
        "revenues",
        "revenue",
        "total net sales",
        "net sales",
        "net revenues",
        "total net revenues",
        "sales",
    ],
    "gross_profit": ["gross profit", "gross margin"],
    "operating_income": ["operating income", "income from operations", "operating profit"],
    "net_income": ["net income attributable to", "net income", "net earnings", "net income (loss)"],
    "eps_diluted": [
        "diluted earnings per share",
        "earnings per share*diluted",
        "net income per share*diluted",
        "earnings per common share*diluted",
    ],
    "rnd": ["research and development", "research, development and related expenses"],
    "sga": ["selling, general and administrative", "selling general and administrative"],
    "depreciation_amortization": [
        "depreciation and amortization",
        "depreciation, depletion and amortization",
    ],
    "operating_cash_flow": [
        "net cash provided by operating activities",
        "net cash provided by (used in) operating activities",
        "cash provided by operating activities",
        "net cash from operating activities",
    ],
    "capex": [
        "purchases of property, plant and equipment",
        "capital expenditures",
        "purchases of property and equipment",
        "additions to property, plant and equipment",
        "payments for property, plant and equipment",
    ],
    "free_cash_flow": ["free cash flow"],
    "cash": ["cash and cash equivalents"],
    "total_assets": ["total assets"],
    "total_liabilities": ["total liabilities"],
    "long_term_debt": ["long-term debt", "long term debt"],
    "dividends_paid": ["dividends paid", "dividends paid to shareholders", "cash dividends paid"],
}

_YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
_UNIT = re.compile(r"\b(?:in\s+)?(thousands|millions|billions)\b", re.I)
_NUM = re.compile(r"^\(?-?\$?\(?\s*([\d,]+(?:\.\d+)?)\s*\)?\s*%?\)?$")


def norm(label: str) -> str:
    s = label.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*\([^)]*\)", "", s)  # "(PP&E)", "(non-GAAP measure)", "(1)"
    s = re.sub(r"[^a-z0-9,'&\- ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,:")


def parse_number(cell: str) -> float | None:
    """'$(1,577)' → -1577, '22.2 %' → 22.2, '—' → None."""
    s = cell.strip().replace(" ", "")
    if not s or s in {"—", "–", "-", "$—", "$-", "n/a", "N/A", "nm", "NM"}:
        return None
    m = _NUM.match(s)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    negative = s.startswith("(") or s.startswith("$(") or s.startswith("-") or s.startswith("$-")
    return -value if negative else value


def _unit(block: BlockRow) -> str | None:
    for text in (block.caption, block.lead_in, " ".join(block.header or [])):
        m = _UNIT.search(text or "")
        if m:
            return m.group(1).lower()
    return None


def _match(label: str, names: list[str], group: str = "") -> tuple[float, int]:
    """(quality, -name rank): 3 exact, 2 prefix (`net income attributable to 3M`) or all parts of a
    `a*b` pattern in order (also across the row's group heading), 1 contained (long names only), 0 none.
    Earlier names in the list win ties: `net income attributable to` beats `net income including …`."""
    n = norm(label)
    if not n or ("per share" in n and not any("per share" in x for x in names)):
        return (0.0, 0)
    full = f"{norm(group)} {n}".strip()
    best = (0.0, 0)
    for rank, name in enumerate(names):
        if "*" in name:
            parts = [norm(x) for x in name.split("*")]
            q = 2.0 if _in_order(n, parts) or _in_order(full, parts) else 0.0
        else:
            x = norm(name)
            if n == x:
                q = 3.0
            elif n.startswith(x + " ") or n.startswith(x + ","):
                q = 2.0
            elif len(x.split()) >= 3 and x in n:
                q = 1.0
            else:
                q = 0.0
        if q and (q, -rank) > best:
            best = (q, -rank)
    return best


def _in_order(text: str, parts: list[str]) -> bool:
    pos = 0
    for part in parts:
        i = text.find(part, pos)
        if i < 0:
            return False
        pos = i + len(part)
    return True


def _labelled_rows(block: BlockRow) -> list[tuple[str, str, list[str]]]:
    """(group, label, values). A label wrapped over two rows is joined ('Purchases and proceeds … marketable'
    + 'securities …'); a row with no values followed by a capitalised label is a group heading."""
    out: list[tuple[str, str, list[str]]] = []
    pending, group = "", ""
    for row in block.rows or []:
        label, values = (row[0] if row else ""), list(row[1:])
        if not any(v.strip() for v in values):
            pending = label
            continue
        if pending and label[:1].islower():
            label = f"{pending} {label}"
        elif pending:
            group = pending
        pending = ""
        out.append((group, label, values))
    return out


@dataclass
class MetricValue:
    doc_id: str
    doc_title: str
    metric: str
    year: int
    value: float | None
    raw: str
    unit: str | None
    label: str
    page: int
    bbox: list[float]
    block_id: str
    table: str


def resolve(metrics: list[str]) -> dict[str, list[str]]:
    """Known metric ids map to their label lists; anything else is searched as a label itself."""
    out = {}
    for m in metrics:
        key = m.strip()
        if not key:
            continue
        out[key] = METRICS.get(key.lower().replace(" ", "_"), [key])
    if not out:
        raise PdfctxError("metrics must be a non-empty list")
    return out


def extract(
    store: Store, metrics: list[str], years: list[int] | None = None, doc_ids: list[str] | None = None
) -> dict:
    wanted = resolve(metrics)
    docs = [d for d in store.list_documents() if d.status == "ok" and (doc_ids is None or d.id in doc_ids)]
    if doc_ids is not None:
        for d in doc_ids:
            store.get_document(d)  # unknown id → NotFound
    found: list[MetricValue] = []
    missing: list[dict] = []
    for doc in docs:
        best: dict[tuple[str, int], tuple[tuple, MetricValue]] = {}
        years_seen: set[int] = set()
        for block in store.tables_for(doc.id):
            cols = [
                (i, int(m.group(1))) for i, h in enumerate(block.header or []) if (m := _YEAR.search(h or ""))
            ]
            if not cols:
                continue
            years_seen.update(y for _, y in cols)
            unit = _unit(block)
            statement = (
                1 if re.search(r"consolidated (statement|balance sheet)", block.caption or "", re.I) else 0
            )
            table_name = " · ".join(x for x in (block.lead_in, block.caption) if x)[:200]
            for group, label, values in _labelled_rows(block):
                for metric, names in wanted.items():
                    quality, rank = _match(label, names, group)
                    if not quality:
                        continue
                    for i, year in cols:
                        if years and year not in years:
                            continue
                        raw = values[i].strip() if i < len(values) else ""
                        value = parse_number(raw)
                        if value is None:
                            continue
                        key = (quality, rank, statement, -block.page)
                        row_unit = (
                            "per share"
                            if "per share" in norm(f"{group} {label}")
                            else ("%" if raw.endswith("%") else unit)
                        )
                        mv = MetricValue(
                            doc.id,
                            doc.title,
                            metric,
                            year,
                            value,
                            raw,
                            row_unit,
                            label,
                            block.page,
                            list(block.bbox),
                            block.id,
                            table_name,
                        )
                        if (metric, year) not in best or key > best[(metric, year)][0]:
                            best[(metric, year)] = (key, mv)
        target_years = sorted(set(years)) if years else sorted(years_seen, reverse=True)[:3]
        for metric in wanted:
            for year in target_years:
                if (metric, year) in best:
                    found.append(best[(metric, year)][1])
                else:
                    missing.append({"doc_id": doc.id, "doc_title": doc.title, "metric": metric, "year": year})
    found.sort(key=lambda v: (v.doc_title, list(wanted).index(v.metric), -v.year))
    return {
        "metrics": list(wanted),
        "years": sorted(set(years)) if years else None,
        "values": [asdict(v) for v in found],
        "missing": missing,
    }


def to_csv(result: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["document", "metric", "year", "value", "unit", "as_reported", "row_label", "page", "block_id"]
    )
    for v in result["values"]:
        w.writerow(
            [
                v["doc_title"],
                v["metric"],
                v["year"],
                v["value"],
                v["unit"] or "",
                v["raw"],
                v["label"],
                v["page"],
                v["block_id"],
            ]
        )
    for m in result["missing"]:
        w.writerow([m["doc_title"], m["metric"], m["year"], "", "", "", "not found", "", ""])
    return buf.getvalue()
