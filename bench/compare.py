"""Paired bootstrap of a system against the baseline on saved per-question results.

python3 -m bench.compare doc pdfctx-tables
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def ranks(scope: str, system: str) -> dict[str, int | None]:
    report = json.loads((RESULTS / f"{scope}-{system}.json").read_text())
    return {q["id"]: q["rank"] for q in report["per_question"]}


def paired(base: dict, other: dict, k: int, rounds: int = 10_000, seed: int = 0) -> dict:
    ids = sorted(base)
    diffs = [
        int(other[i] is not None and other[i] <= k) - int(base[i] is not None and base[i] <= k) for i in ids
    ]
    rng = random.Random(seed)
    boot = sorted(sum(rng.choice(diffs) for _ in ids) / len(ids) for _ in range(rounds))
    return {
        "k": k,
        "diff": sum(diffs) / len(ids),
        "ci95": (boot[int(0.025 * rounds)], boot[int(0.975 * rounds) - 1]),
        "wins": sum(d > 0 for d in diffs),
        "losses": sum(d < 0 for d in diffs),
    }


def main(argv: list[str]) -> None:
    scope, system = argv[0], argv[1]
    base, other = ranks(scope, "baseline"), ranks(scope, system)
    print(f"| k | {system} − baseline | 95% CI | wins | losses |\n|---|---|---|---|---|")
    for k in (1, 3, 5, 10):
        r = paired(base, other, k)
        lo, hi = r["ci95"]
        print(f"| {k} | {r['diff']:+.3f} | [{lo:+.3f}, {hi:+.3f}] | {r['wins']} | {r['losses']} |")


if __name__ == "__main__":
    main(sys.argv[1:])
