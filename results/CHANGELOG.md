# Retrieval changes, measured

FinanceBench open set, 150 questions, doc scope unless noted. R@k = evidence-page recall@k,
tok = mean tokens of the top-5 passages. Every change was kept or reverted on these numbers.

## Starting point (v0, BM25 only, no page logic)

| system | R@1 | R@3 | R@5 | R@10 | MRR | tok |
|---|---|---|---|---|---|---|
| baseline (page BM25) | 0.147 | 0.233 | 0.360 | 0.507 | 0.230 | 4615 |
| structure | 0.180 | 0.280 | 0.313 | 0.440 | 0.247 | 769 |
| + context prefix | 0.147 | 0.273 | 0.327 | 0.400 | 0.224 | 903 |
| + table rows | 0.153 | 0.287 | 0.340 | 0.433 | 0.237 | 839 |

Small units win at rank 1 and cost 6× fewer tokens, but lose recall@5/10. The miss analysis showed two causes:
the top-5 wasted slots on several blocks from the same page, and a page with several matching blocks (strong
evidence) was not rewarded.

## Kept

1. **One result per page** (`per_page_cap=1`): tables R@10 0.433 → 0.500.
2. **Page evidence boost** (small-to-big). Each unit gets `page_boost ×` the score of the best *other* match on its
   page. A first version summed all other matches (R@5 0.420). It was replaced because a unit test showed that
   a page full of weak boilerplate matches could beat a strong answer elsewhere. The bounded version scores
   slightly lower and is robust.
3. **More candidates** (`k_candidates` 50 → 200) and **context weight 1.0** (was 0.5): R@1 0.153 → 0.180.
4. **Most specific match**: when a whole table and one of its rows both match, return the row (same page,
   fewer tokens).

Defaults were rounded (`page_boost=1.0`, not the best grid value 0.35), so they are not fitted to 150 questions.

| setting (tables index) | R@1 | R@3 | R@5 | R@10 | MRR | tok |
|---|---|---|---|---|---|---|
| cap1 | 0.153 | 0.293 | 0.347 | 0.500 | 0.249 | 898 |
| cap1 + sum-boost 0.5 | 0.133 | 0.287 | 0.420 | 0.533 | 0.245 | 631 |
| cap1 + sum-boost 0.35, k200, cw1 (best grid point) | 0.180 | 0.333 | 0.447 | 0.580 | 0.294 | 475 |
| cap1 + max-boost 0.0, k200, cw1 | 0.187 | 0.313 | 0.367 | 0.513 | 0.274 | 789 |
| **cap1 + max-boost 1.0, k200, cw1 (default)** | **0.160** | **0.307** | **0.400** | **0.553** | **0.263** | **461** |

## Reverted

- **Document routing for corpus scope** (score documents by their top-3 units and keep the top N): R@10 fell from
  0.193 to 0.120 / 0.153 / 0.153 for N = 1 / 2 / 3.
- **Sum-of-page boost**: see Kept 2.

## Corpus scope

The defaults were not tuned on corpus scope, but one corpus-scope change (document routing) was tried
and reverted, so this table is not fully untouched.

| system | R@1 | R@3 | R@5 | R@10 | MRR | tok |
|---|---|---|---|---|---|---|
| baseline | 0.093 | 0.107 | 0.120 | 0.187 | 0.112 | 4791 |
| pdfctx-tables | 0.073 | 0.127 | 0.147 | 0.200 | 0.108 | 399 |

The result is mixed: higher recall@3–10 at 12× fewer tokens, but lower rank-1. Most misses come from finding the
right filing among 84 similar 10-Ks. That is the next thing to work on, for example dense vectors.

## Re-run after the index-version fix

Earlier runs reused indexes built by an older parser, so parser fixes (year-as-section-number, table headers
as headings) were not measured. `INDEX_VERSION` now forces a rebuild. Fresh numbers, single-document scope:

| system | R@1 | R@3 | R@5 | R@10 | MRR | tok |
|---|---|---|---|---|---|---|
| baseline | 0.147 | 0.233 | 0.360 | 0.507 | 0.230 | 4615 |
| pdfctx-structure | 0.160 | 0.267 | 0.333 | 0.453 | 0.237 | 586 |
| pdfctx-context | 0.160 | 0.267 | 0.353 | 0.500 | 0.242 | 572 |
| pdfctx-tables | 0.167 | 0.313 | 0.393 | 0.567 | 0.270 | 461 |

The default improved slightly (R@10 0.553 → 0.567); the corpus table above is also from the fresh run.
