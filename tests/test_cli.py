from __future__ import annotations

import json
import shutil

from pdfctx.cli import main
from tests import pdfgen


def test_version(capsys):
    try:
        main(["--version"])
    except SystemExit as e:
        assert e.code == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_no_command_is_usage_error(capsys):
    assert main([]) == 2


def test_cli_index_then_search(tmp_path, report_pdf, capsys):
    folder = tmp_path / "docs"
    folder.mkdir()
    shutil.copy(report_pdf, folder / "report.pdf")
    assert main(["index", str(folder)]) == 0
    assert (folder / ".pdfctx" / "index.db").exists()
    capsys.readouterr()
    assert main(["search", "termination notice", "--db", str(folder / ".pdfctx" / "index.db")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("p.4") and "ninety days" in out


def test_cli_outline_by_path(tmp_path, report_pdf, capsys):
    pdf = tmp_path / "r.pdf"
    shutil.copy(report_pdf, pdf)
    main(["index", str(pdf)])
    capsys.readouterr()
    assert main(["outline", str(pdf), "--db", str(tmp_path / ".pdfctx" / "index.db")]) == 0
    out = capsys.readouterr().out
    assert pdfgen.REPORT_TITLE in out and "    2.1 Revenue" in out


def test_cli_audit(tmp_path, report_pdf, capsys):
    pdf = tmp_path / "r.pdf"
    shutil.copy(report_pdf, pdf)
    db = str(tmp_path / ".pdfctx" / "index.db")
    main(["index", str(pdf)])
    main(["search", "revenue", "--db", db])
    capsys.readouterr()
    assert main(["audit", "--json", "--db", db]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["tool"] for r in rows] == ["list_documents", "search"]
    assert rows[1]["client"] == "cli" and rows[1]["args"]["query"] == "revenue"


def test_cli_bad_path_exit_1(tmp_path, capsys):
    assert main(["index", str(tmp_path / "missing")]) == 1
    assert "no such file" in capsys.readouterr().err
    assert main(["search", "x", "--db", str(tmp_path / "none.db")]) == 1


def test_cli_serve_stdio_end_to_end(tmp_path, report_pdf):
    """A real MCP client launching `pdfctx serve` as a subprocess, like Claude Desktop does."""
    import os
    import sys
    from pathlib import Path

    import anyio
    from mcp import Client, StdioServerParameters

    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": f"{root / 'src'}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pdfctx.cli", "serve", str(report_pdf), "--db", str(tmp_path / "i.db")],
        env=env,
    )

    async def go():
        async with Client(params) as c:
            res = await c.call_tool("search", {"query": "termination notice period", "k": 1})
            return res.structured_content

    out = anyio.run(go)
    assert pdfgen.TERMINATION_SENTENCE in out["results"][0]["text"]
