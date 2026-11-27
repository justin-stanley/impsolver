"""Run the worked examples and write their output into docs/examples/generated/.

    python docs/examples/run_examples.py          # regenerate
    python docs/examples/run_examples.py --check  # fail if the committed output is stale

The docs pages include these files, so the numbers on the site always come from the code.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import shlex
import sys
from pathlib import Path

from impsolver.cli import build_parser, main

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "generated"

EXAMPLES: dict[str, list[str]] = {
    "backtest": ["backtest"],
    "evaluate": ["evaluate", "examples/scenario-example.yaml"],
    "flips": ["flips", "examples/scenario-example.yaml", "--gate", "S2"],
    "simulate": ["simulate", "examples/scenario-example.yaml", "--draws", "20000"],
    "simulate-cabinet-a": ["simulate", "examples/scenario-cabinet-a.yaml", "--draws", "20000"],
    "simulate-national": [
        "simulate", "examples/scenario-cabinet-a-national.yaml", "--draws", "20000",
    ],
    "viability": [
        "viability", "examples/scenario-cabinet-a.yaml", "examples/scenario-cabinet-b.yaml",
        "--draws", "4000",
    ],
    "portfolio": ["portfolio", "examples/portfolio-example.yaml"],
    "calibrate": ["calibrate", "--alignment", "alignment/us-116.json", "--permutations", "2000"],
}  # fmt: skip


def run(args: list[str]) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(args)
    if rc != 0:
        raise SystemExit(f"example failed ({rc}): impsolver {shlex.join(args)}")
    return buf.getvalue()


def cli_reference() -> str:
    parser = build_parser()
    parts = ["```text", parser.format_help().rstrip(), "```"]
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    for name, p in sub.choices.items():  # type: ignore[attr-defined]
        if name in ("roster", "align"):
            continue
        parts += [f"\n### `impsolver {name}`\n", "```text", p.format_help().rstrip(), "```"]
    return "\n".join(parts) + "\n"


def render() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, args in EXAMPLES.items():
        text = run(args).rstrip()
        out[f"{name}.md"] = f"```console\n$ impsolver {shlex.join(args)}\n{text}\n```\n"
    out["cli.md"] = cli_reference()
    return out


def main_() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    import os

    os.chdir(ROOT)
    os.environ["COLUMNS"] = "100"  # argparse wraps help to the terminal width
    files = render()
    stale = [
        n
        for n, t in files.items()
        if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != t
    ]
    if a.check:
        if stale:
            print("stale generated docs: " + ", ".join(stale), file=sys.stderr)
            print("run: python docs/examples/run_examples.py", file=sys.stderr)
            return 1
        print("generated docs are current")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n, t in files.items():
        (OUT / n).write_text(t, encoding="utf-8")
    print(f"wrote {len(files)} files to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_())
