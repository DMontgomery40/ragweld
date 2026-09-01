#!/usr/bin/env python3
"""Create evaluation dataset from repository."""

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path


def create_eval_dataset(
    repo_path: str,
    output_path: str,
    num_questions: int = 20,
) -> None:
    """Create evaluation dataset by sampling files and generating questions."""
    repo = Path(repo_path)
    if not repo.exists():
        print(f"Repository not found: {repo_path}")
        return

    # Find code files
    code_extensions = {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java"}
    code_files = [
        f for f in repo.rglob("*")
        if f.is_file() and f.suffix in code_extensions and "node_modules" not in str(f)
    ]

    if not code_files:
        print("No code files found")
        return

    # Sample files for questions
    import random
    sampled_files = random.sample(code_files, min(num_questions, len(code_files)))

    dataset = []
    for file_path in sampled_files:
        relative_path = file_path.relative_to(repo)

        # Generate simple questions based on file content
        entry = {
            "entry_id": str(uuid.uuid4()),
            "question": f"How does {relative_path.stem} work?",
            "expected_chunks": [str(relative_path)],
            "expected_answer": None,
            "tags": [file_path.suffix.lstrip(".")],
            "created_at": datetime.now(UTC).isoformat(),
        }
        dataset.append(entry)

    with open(output_path, "w") as f:
        json.dump(dataset, f, indent=2)

    print(f"Created evaluation dataset with {len(dataset)} entries")
    print(f"Saved to: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create evaluation dataset")
    parser.add_argument("--repo", required=True, help="Repository path")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--num-questions", type=int, default=20, help="Number of questions")
    args = parser.parse_args()

    create_eval_dataset(args.repo, args.output, args.num_questions)


if __name__ == "__main__":
    main()
