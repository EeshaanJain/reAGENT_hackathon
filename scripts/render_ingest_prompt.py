#!/usr/bin/env python3
"""Render a benchmark dataset-ingest prompt from YAML configuration."""

from __future__ import annotations

import argparse
from pathlib import Path

from psls_tooling import render_ingest_prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="Path to a dataset.yaml file")
    parser.add_argument("--output", type=Path, help="Write to a file instead of stdout")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rendered = render_ingest_prompt(args.config)
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
