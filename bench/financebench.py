"""FinanceBench retrieval benchmark: evidence-page recall, MRR, tokens and latency.

    python -m bench.financebench --systems baseline,pdfctx-structure,pdfctx-tables --scope doc

Data (CC BY-NC 4.0) is downloaded into $PDFCTX_BENCH_DIR (default ~/.cache/pdfctx-bench) at the pinned
commit below and is never committed to this repository.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = "https://github.com/patronus-ai/financebench"
COMMIT = "cc39aeb4afdf33909ee1412188bf89035950c2eb"
BENCH_DIR = Path(os.environ.get("PDFCTX_BENCH_DIR", Path.home() / ".cache" / "pdfctx-bench"))
RESULTS = Path(__file__).parent / "results"
KS = (1, 3, 5, 10)


@dataclass
class Question:
    id: str
    doc_name: str
    question: str
    answer: str
    evidence: set[tuple[str, int]]  # (doc_name, 1-based page)
    evidence_texts: list[str]
    kind: str = ""


@dataclass
class Passage:
    doc_name: str
    page: int
    text: str


def tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def ensure_data(bench_dir: Path = BENCH_DIR) -> None:
    """Fetch the questions and the PDFs they need (sparse, pinned commit)."""
    questions = bench_dir / "data" / "financebench_open_source.jsonl"
    bench_dir.mkdir(parents=True, exist_ok=True)
    if not questions.exists():
        if not (bench_dir / ".git").exists():
            _git("init", "-q", cwd=bench_dir)
            _git("remote", "add", "origin", REPO, cwd=bench_dir)
        _git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", COMMIT, cwd=bench_dir)
        _git("checkout", "-q", "FETCH_HEAD", "--", "data", cwd=bench_dir)
    missing = [f"pdfs/{d}.pdf" for d in sorted({q.doc_name for q in load(bench_dir)})]
    missing = [m for m in missing if not (bench_dir / m).exists()]
    if missing:
        print(f"downloading {len(missing)} PDFs…", file=sys.stderr)
        _git("checkout", "-q", "FETCH_HEAD", "--", *missing, cwd=bench_dir)


def load(bench_dir: Path = BENCH_DIR) -> list[Question]:
    out = []
    for line in (bench_dir / "data" / "financebench_open_source.jsonl").read_text().splitlines():
        r = json.loads(line)
        out.append(
            Question(
                id=r["financebench_id"],
                doc_name=r["doc_name"],
                question=r["question"],
                answer=r["answer"],
                evidence={(e["doc_name"], int(e["evidence_page_num"]) + 1) for e in r["evidence"]},
                evidence_texts=[e["evidence_text"] for e in r["evidence"]],
                kind=r.get("question_type", ""),
            )
        )
    return out


def hit_rank(q: Question, passages: list[Passage]) -> int | None:
    for rank, p in enumerate(passages, start=1):
        if (p.doc_name, p.page) in q.evidence:
            return rank
    return None


def score(questions: list[Question], results: dict[str, list[Passage]], latencies_ms: list[float]) -> dict:
    n = len(questions)
    ranks = [hit_rank(q, results.get(q.id, [])[:10]) for q in questions]
    metrics = {f"page_recall@{k}": sum(1 for r in ranks if r and r <= k) / n for k in KS}
    metrics["mrr@10"] = sum(1 / r for r in ranks if r) / n
    metrics["tokens@5"] = sum(sum(tokens(p.text) for p in results.get(q.id, [])[:5]) for q in questions) / n
    metrics["latency_p50_ms"] = statistics.median(latencies_ms) if latencies_ms else 0.0
    return metrics


def run(system_names: list[str], scope: str, limit: int | None, bench_dir: Path = BENCH_DIR) -> list[dict]:
    from bench.systems import make_system

    ensure_data(bench_dir)
    questions = load(bench_dir)[:limit] if limit else load(bench_dir)
    pdfs = sorted({bench_dir / "pdfs" / f"{q.doc_name}.pdf" for q in questions})
    RESULTS.mkdir(exist_ok=True)
    reports = []
    for name in system_names:
        system = make_system(name, bench_dir)
        t0 = time.time()
        try:
            system.prepare(pdfs)
        except ImportError as e:
            print(f"skip {name}: {e}", file=sys.stderr)
            continue
        prep_s = time.time() - t0
        results, latencies, per_q = {}, [], []
        for q in questions:
            t = time.perf_counter()
            passages = system.retrieve(q.question, q.doc_name if scope == "doc" else None, k=10)
            latencies.append((time.perf_counter() - t) * 1000)
            results[q.id] = passages
            per_q.append(
                {
                    "id": q.id,
                    "kind": q.kind,
                    "rank": hit_rank(q, passages),
                    "evidence": sorted(p for _, p in q.evidence),
                    "top_pages": [p.page for p in passages[:5]],
                }
            )
        metrics = score(questions, results, latencies)
        report = {
            "system": name,
            "scope": scope,
            "questions": len(questions),
            "metrics": {k: round(v, 4) for k, v in metrics.items()},
            "prepare_s": round(prep_s, 1),
            "version": getattr(system, "version", ""),
            "financebench_commit": COMMIT,
            "date": datetime.now(UTC).date().isoformat(),
            "per_question": per_q,
        }
        (RESULTS / f"{scope}-{name}.json").write_text(json.dumps(report, indent=1) + "\n")
        reports.append(report)
        print(f"{name}: {report['metrics']}", file=sys.stderr)
    print(table(reports))
    return reports


def table(reports: list[dict]) -> str:
    cols = [
        "page_recall@1",
        "page_recall@3",
        "page_recall@5",
        "page_recall@10",
        "mrr@10",
        "tokens@5",
        "latency_p50_ms",
    ]
    head = "| system | " + " | ".join(c.replace("page_recall", "R") for c in cols) + " |"
    lines = [head, "|" + "---|" * (len(cols) + 1)]
    for r in reports:
        m = r["metrics"]
        cells = [f"{m[c]:.3f}" if c.startswith(("page", "mrr")) else f"{m[c]:.0f}" for c in cols]
        lines.append(f"| {r['system']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default="baseline,pdfctx-structure,pdfctx-context,pdfctx-tables")
    ap.add_argument("--scope", choices=["doc", "corpus"], default="doc")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)
    run(args.systems.split(","), args.scope, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
