"""Rewrite only the pilot codebook and instructions; no model, store or key access."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from beautyads.eval.sheets import (
    SheetError,
    codebook_rows,
    instructions_text,
    write_docs_files,
)

DEFAULT_OUT_DIR = Path("data/interim/pilot")


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        files = write_docs_files(args.out_dir, codebook_rows(), instructions_text())
    except SheetError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    except OSError:
        print("PREFLIGHT_FAILED DOCS_NOT_WRITABLE", file=out)
        return 2
    for name, path in files.items():
        print(f"{name} {path}", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
