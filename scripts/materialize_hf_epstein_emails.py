#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.synthetic.hf_epstein_emails import (
    HF_CONFIG,
    HF_DATASET,
    HF_SPLIT,
    materialize_epstein_email_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize the Hugging Face Epstein email dataset into a fresh text corpus and eval set."
    )
    parser.add_argument("--output-dir", required=True, help="Directory to write materialized email text files into.")
    parser.add_argument(
        "--eval-output",
        default="data/eval_datasets/epstein-files-1.json",
        help="Eval dataset JSON to write from the same source rows.",
    )
    parser.add_argument(
        "--manifest-output",
        default=None,
        help="Optional sidecar manifest JSON path. If omitted, the manifest is only printed to stdout.",
    )
    parser.add_argument("--dataset", default=HF_DATASET, help="HF dataset id.")
    parser.add_argument("--config", default=HF_CONFIG, help="HF dataset config.")
    parser.add_argument("--split", default=HF_SPLIT, help="HF dataset split.")
    parser.add_argument("--batch-size", type=int, default=100, help="HF rows batch size (HF rows endpoint max is 100).")
    parser.add_argument("--max-eval-rows", type=int, default=200, help="Maximum eval rows to emit.")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for quick experiments.")
    parser.add_argument("--replace", action="store_true", help="Delete the output dir before writing.")
    args = parser.parse_args()

    manifest = materialize_epstein_email_dataset(
        output_dir=Path(args.output_dir).expanduser(),
        eval_output_path=Path(args.eval_output).expanduser() if args.eval_output else None,
        manifest_output_path=Path(args.manifest_output).expanduser() if args.manifest_output else None,
        dataset=args.dataset,
        config=args.config,
        split=args.split,
        batch_size=args.batch_size,
        max_eval_rows=args.max_eval_rows,
        limit=args.limit,
        replace=bool(args.replace),
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
