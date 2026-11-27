"""OCR for pages without a text layer, via the tesseract binary (optional; no Python dependency).

Recognised words become the same `Word` objects as the text layer, so columns, tables, headings and
citation boxes work unchanged on scanned pages.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .model import Word

DPI = 300
MIN_CONFIDENCE = 50
TIMEOUT_S = 60


def available() -> bool:
    """OCR runs when tesseract is installed, unless PDFCTX_OCR=0."""
    return os.environ.get("PDFCTX_OCR", "1") != "0" and shutil.which("tesseract") is not None


def language() -> str:
    return os.environ.get("PDFCTX_OCR_LANG", "eng")


def ocr_image(image: Image.Image, scale: float) -> list[Word]:
    """Words on a page image rendered at `scale` (pixels per point), in page points with top-left origin."""
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "page.png"
        image.save(png)
        proc = subprocess.run(
            ["tesseract", str(png), "stdout", "-l", language(), "--psm", "3", "tsv"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract failed: {proc.stderr.strip()[:200]}")
    return parse_tsv(proc.stdout, scale)


def parse_tsv(tsv: str, scale: float) -> list[Word]:
    rows = [
        r
        for r in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
        if r.get("level") == "5" and (r.get("text") or "").strip()
    ]
    rows = [r for r in rows if float(r["conf"]) >= MIN_CONFIDENCE]
    # Font size from the line's median word height: single words (x-height vs. cap height) vary too much.
    heights: dict[tuple[str, str, str], list[int]] = {}
    for r in rows:
        heights.setdefault((r["block_num"], r["par_num"], r["line_num"]), []).append(int(r["height"]))
    words = []
    for r in rows:
        hs = sorted(heights[(r["block_num"], r["par_num"], r["line_num"])])
        size = round(hs[len(hs) // 2] / scale * 2) / 2
        left, top = int(r["left"]) / scale, int(r["top"]) / scale
        words.append(
            Word(
                text=r["text"].strip(),
                x0=round(left, 1),
                top=round(top, 1),
                x1=round(left + int(r["width"]) / scale, 1),
                bottom=round(top + int(r["height"]) / scale, 1),
                size=size,
                bold=False,
            )
        )
    return words
