#!/usr/bin/env python3
"""Quick setup script for development environment."""

import os
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path | None = None) -> bool:
    """Run a command and return success status."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode == 0


def main() -> None:
    project_root = Path(__file__).parent.parent

    print("=== TriBridRAG Quick Setup ===\n")

    # Check for .env file
    env_file = project_root / ".env"
    env_example = project_root / ".env.example"
    if not env_file.exists() and env_example.exists():
        print("Creating .env from .env.example...")
        env_file.write_text(env_example.read_text())
        print("Please edit .env with your API keys\n")

    # Install Python dependencies
    print("Installing Python dependencies...")
    if not run_cmd(["uv", "sync"], cwd=project_root):
        print("Failed to install Python dependencies")
        sys.exit(1)

    # Install frontend dependencies
    print("\nInstalling frontend dependencies...")
    web_dir = project_root / "web"
    if not run_cmd(["npm", "install"], cwd=web_dir):
        print("Failed to install frontend dependencies")
        sys.exit(1)

    # Check Docker
    print("\nChecking Docker...")
    if not run_cmd(["docker", "compose", "version"]):
        print("Docker Compose not found. Please install Docker.")
        sys.exit(1)

    print("\n=== Setup Complete! ===")
    print("\nNext steps:")
    print("1. Edit .env with your API keys")
    print("2. Start and select your host-owned Docker/Colima runtime")
    print("3. Run: ./start.sh")
    print("4. Open http://localhost:55173/web/")


if __name__ == "__main__":
    main()
