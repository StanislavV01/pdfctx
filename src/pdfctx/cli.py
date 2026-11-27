from __future__ import annotations

import argparse
import sys

from pdfctx import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pdfctx", description=__doc__)
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
