"""Finance vocabulary for lexical search: the words a filing uses for what a question asks.

Questions say "capital expenditure"; the cash flow statement says "Purchases of property, plant and
equipment". BM25 cannot bridge that alone. Each entry adds the statement's own line-item words to the
query. The entries are standard accounting definitions, written from line items (not from benchmark
questions).
"""

from __future__ import annotations

import re

GLOSSARY: list[tuple[str, str]] = [
    (r"capex|capital expenditures?|capital spending", "purchases of property plant equipment additions"),
    (r"revenues?|top line|turnover\b(?! ratio)", "net sales total revenues"),
    (r"net income|net profit|net earnings|bottom line", "net income attributable earnings"),
    (r"cogs|cost of goods sold", "cost of sales cost of goods sold"),
    (r"gross (?:margin|profit)", "gross profit net sales cost of sales"),
    (r"operating (?:income|profit|margin)|\bebit\b", "operating income income from operations"),
    (r"\bebitda\b", "operating income depreciation amortization"),
    (
        r"operating cash flows?|cash (?:flow )?from operations|\bcfo\b",
        "net cash provided by operating activities",
    ),
    (
        r"free cash flow|\bfcf\b",
        "net cash provided by operating activities purchases of property plant equipment",
    ),
    (r"\bd&a\b|depreciation", "depreciation amortization"),
    (r"working capital", "total current assets total current liabilities"),
    (r"current ratio|quick ratio|liquidity", "total current assets total current liabilities inventories"),
    (r"inventory turnover|days inventory", "cost of sales inventories"),
    (r"receivables? turnover|days sales outstanding|\bdso\b", "accounts receivable net sales"),
    (r"payables? turnover|days payables?|\bdpo\b", "accounts payable cost of sales"),
    (r"return on assets|\broa\b", "net income total assets"),
    (r"return on equity|\broe\b", "net income total shareholders equity"),
    (r"debt[- ]to[- ]equity|leverage|total debt", "long-term debt short-term borrowings total equity"),
    (r"interest coverage", "operating income interest expense"),
    (r"effective tax rate|tax rate", "provision for income taxes income before income taxes effective"),
    (r"dividends?|payout ratio", "cash dividends declared paid per share"),
    (r"\beps\b|earnings per share", "earnings per share diluted basic"),
    (
        r"buybacks?|share repurchases?|repurchased? shares",
        "purchases of treasury stock repurchases common stock",
    ),
    (r"fixed asset turnover|\bppe\b|pp&e", "property plant equipment net"),
    (r"asset turnover", "total assets net sales revenues"),
    (r"r&d|research and development", "research development expenses"),
    (r"\bsg&a\b|selling,? general", "selling general administrative expenses"),
    (r"cash conversion", "net cash provided by operating activities net income"),
    (r"unadjusted|gaap", "consolidated statement"),
]

_COMPILED = [(re.compile(p, re.I), words) for p, words in GLOSSARY]


def expand(query: str) -> str:
    """The query plus the line-item words of every term it mentions (unchanged if none match)."""
    extra = [words for pattern, words in _COMPILED if pattern.search(query)]
    return " ".join([query, *extra]) if extra else query
