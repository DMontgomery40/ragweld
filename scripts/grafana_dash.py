#!/usr/bin/env python3
"""Provision Grafana dashboard."""

import argparse
import json
from pathlib import Path

import httpx


def provision_dashboard(grafana_url: str, dashboard_path: str, api_key: str | None = None) -> None:
    """Upload dashboard to Grafana."""
    dashboard_file = Path(dashboard_path)
    if not dashboard_file.exists():
        print(f"Dashboard file not found: {dashboard_path}")
        return

    with open(dashboard_file) as f:
        dashboard = json.load(f)

    # Wrap in Grafana API format
    payload = {
        "dashboard": dashboard,
        "overwrite": True,
        "message": "Provisioned by tribrid-rag",
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{grafana_url.rstrip('/')}/api/dashboards/db"

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            result = response.json()
            print("Dashboard provisioned successfully")
            print(f"  URL: {grafana_url}/d/{result.get('uid')}")
        else:
            print(f"Failed to provision dashboard: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error provisioning dashboard: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision Grafana dashboard")
    parser.add_argument(
        "--grafana-url",
        default="http://localhost:3000",
        help="Grafana URL",
    )
    parser.add_argument(
        "--dashboard",
        default="infra/grafana/provisioning/dashboards/rag-metrics.json",
        help="Dashboard JSON file",
    )
    parser.add_argument("--api-key", help="Grafana API key (optional)")
    args = parser.parse_args()

    provision_dashboard(args.grafana_url, args.dashboard, args.api_key)


if __name__ == "__main__":
    main()
