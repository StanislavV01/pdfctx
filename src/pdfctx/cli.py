"""pdfctx — structure-aware, citable PDF retrieval for AI agents."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

from . import __version__
from .embed import get_embedder, get_reranker
from .errors import PdfctxError
from .indexer import IndexOptions, doc_id_for


def default_db(paths: list[Path]) -> Path:
    first = Path(paths[0]) if paths else Path.cwd()
    base = first if first.is_dir() else first.parent
    return base / ".pdfctx" / "index.db"


def _library(args, client: str):
    from .library import Library

    paths = [Path(p) for p in getattr(args, "paths", []) or []]
    for p in paths:
        if not p.exists():
            raise PdfctxError(f"no such file or folder: {p}")
    db = Path(args.db) if args.db else default_db(paths)
    if not paths and not db.exists():
        raise PdfctxError(f"no index at {db}; run `pdfctx index PATH` first or pass --db")
    options = IndexOptions(embedder=get_embedder(args.embed))
    return Library(
        db, roots=paths or None, options=options, reranker=get_reranker(args.rerank), client=client
    )


def _print_outline(sections: list[dict], depth: int = 0) -> None:
    for s in sections:
        print(f"{'  ' * depth}{s['title']}  (p.{s['page']}, {s['id']})")
        _print_outline(s["children"], depth + 1)


def cmd_index(args) -> int:
    lib = _library(args, "cli")
    docs = lib.list_documents()["documents"]
    bad = [d for d in docs if d["status"] != "ok"]
    print(f"indexed {len(docs) - len(bad)} document(s) into {lib.store.path}")
    for d in bad:
        print(
            f"  {d['status']}: {d['file']}" + (f" ({d['error']})" if d.get("error") else ""), file=sys.stderr
        )
    return 0


def cmd_search(args) -> int:
    lib = _library(args, "cli")
    for r in lib.search(args.query, k=args.k)["results"]:
        where = " › ".join(r["section_path"]) or "—"
        print(f"p.{r['page']}  [{r['match']}]  {where}  ({r['block_id']})")
        print(textwrap.indent(textwrap.shorten(r["text"], 400), "    "))
    return 0


def cmd_outline(args) -> int:
    lib = _library(args, "cli")
    target = Path(args.document)
    doc_id = doc_id_for(target) if target.exists() else args.document
    out = lib.outline(doc_id, args.depth)
    print(f"{out['title']}  ({out['pages']} pages, {out['doc_id']})")
    _print_outline(out["sections"], 1)
    return 0


def cmd_audit(args) -> int:
    lib = _library(args, "cli")
    for r in reversed(lib.audit(args.limit)):
        print(
            json.dumps(r, ensure_ascii=False)
            if args.json
            else f"{r['ts']}  {r['client']:<10} {r['tool']:<15} "
            f"{json.dumps(r['args'], ensure_ascii=False)}  → {len(r['block_ids'])} block(s)"
        )
    return 0


def cmd_serve(args) -> int:
    from .mcp_server import build_server

    lib = _library(args, "mcp-stdio")
    print(f"pdfctx {__version__}: MCP on stdio, index {lib.store.path}", file=sys.stderr)
    build_server(lib).run("stdio")
    return 0


def cmd_serve_http(args) -> int:
    import uvicorn

    from .api import create_app

    lib = _library(args, "http")
    app = create_app(lib, upload_dir=Path(args.uploads) if args.uploads else None)
    print(
        f"pdfctx {__version__}: REST http://{args.host}:{args.port}/v1 · MCP http://{args.host}:{args.port}/mcp",
        file=sys.stderr,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdfctx", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command")

    def common(sp, paths: str):
        if paths == "required":
            sp.add_argument("paths", nargs="+", help="PDF files or folders")
        elif paths == "optional":
            sp.add_argument("paths", nargs="*", help="PDF files or folders (re-indexed if changed)")
        sp.add_argument("--db", help="index file (default: <folder>/.pdfctx/index.db)")
        sp.add_argument(
            "--embed", choices=["hash", "fastembed", "openai", "voyage"], help="add dense vectors"
        )
        sp.add_argument("--rerank", choices=["fastembed", "cohere", "voyage"], help="rerank the top results")

    sp = sub.add_parser("index", help="index PDF files or folders")
    common(sp, "required")
    sp.set_defaults(fn=cmd_index)

    sp = sub.add_parser("search", help="search the index")
    sp.add_argument("query")
    sp.add_argument("-k", type=int, default=5)
    common(sp, "none")
    sp.set_defaults(fn=cmd_search, paths=[])

    sp = sub.add_parser("outline", help="print a document's section tree")
    sp.add_argument("document", help="document id or PDF path")
    sp.add_argument("--depth", type=int, default=3)
    common(sp, "none")
    sp.set_defaults(fn=cmd_outline, paths=[])

    sp = sub.add_parser("audit", help="show which tools agents called and what they read")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--json", action="store_true")
    common(sp, "none")
    sp.set_defaults(fn=cmd_audit, paths=[])

    sp = sub.add_parser("serve", help="MCP server over stdio (Claude Desktop, Claude Code, Cursor)")
    common(sp, "required")
    sp.set_defaults(fn=cmd_serve)

    sp = sub.add_parser("serve-http", help="REST API at /v1 and MCP at /mcp")
    common(sp, "optional")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--uploads", help="folder for POST /v1/documents uploads (disabled if not set)")
    sp.set_defaults(fn=cmd_serve_http)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.fn(args)
    except PdfctxError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
