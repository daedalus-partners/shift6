from __future__ import annotations

import argparse
import os
from datetime import date
from typing import Any, Literal

from mcp.server import MCPServer

from .db import SessionLocal
from .services.email.coverage_records import (
    export_records_csv,
    get_record,
    list_clients,
    list_publications,
    search_records,
    summarize_records,
)


mcp = MCPServer(
    "Shift6 Coverage Records",
    instructions=(
        "Read-only access to durable Shift6 coverage records, publication-date provenance, "
        "evidence manifests, versioned score snapshots, and CSV exports. Missing or draft "
        "score inputs are returned explicitly and must not be inferred."
    ),
)


def _date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    return date.fromisoformat(value.strip())


def _filters(
    client_name: str | None,
    publication: str | None,
    start_date: str | None,
    end_date: str | None,
    date_basis: Literal["published", "captured", "generated"],
) -> dict[str, Any]:
    return {
        "client_name": client_name,
        "publication": publication,
        "start_date": _date(start_date),
        "end_date": _date(end_date),
        "date_basis": date_basis,
    }


@mcp.tool()
def list_coverage_clients() -> dict[str, Any]:
    """List clients that have stored coverage records and their record counts."""
    with SessionLocal() as db:
        return {"items": list_clients(db)}


@mcp.tool()
def list_coverage_publications() -> dict[str, Any]:
    """List publications that have stored coverage records and their record counts."""
    with SessionLocal() as db:
        return {"items": list_publications(db)}


@mcp.tool()
def search_coverage_records(
    client_name: str | None = None,
    publication: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    date_basis: Literal["published", "captured", "generated"] = "published",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Search coverage by client, publication domain or name, and an inclusive ISO date range."""
    with SessionLocal() as db:
        return search_records(
            db,
            limit=limit,
            offset=offset,
            **_filters(client_name, publication, start_date, end_date, date_basis),
        )


@mcp.tool()
def get_coverage_record(summary_id: int) -> dict[str, Any]:
    """Get one coverage record, including metric, score, date, and screenshot provenance."""
    with SessionLocal() as db:
        item = get_record(db, summary_id)
        return item or {"error": "coverage_record_not_found", "summary_id": summary_id}


@mcp.tool()
def summarize_coverage_records(
    client_name: str | None = None,
    publication: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    date_basis: Literal["published", "captured", "generated"] = "published",
) -> dict[str, Any]:
    """Summarize record counts and finalized score coverage for the selected slice."""
    with SessionLocal() as db:
        return summarize_records(
            db,
            **_filters(client_name, publication, start_date, end_date, date_basis),
        )


@mcp.tool()
def export_coverage_csv(
    client_name: str | None = None,
    publication: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    date_basis: Literal["published", "captured", "generated"] = "published",
) -> dict[str, Any]:
    """Return a UTF-8 CSV for the selected coverage records (maximum 10,000 rows)."""
    with SessionLocal() as db:
        content, count = export_records_csv(
            db,
            **_filters(client_name, publication, start_date, end_date, date_basis),
        )
        return {
            "filename": f"shift6-coverage-{date.today().isoformat()}.csv",
            "record_count": count,
            "content_type": "text/csv; charset=utf-8",
            "csv": content,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the read-only Shift6 coverage MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("MCP_TRANSPORT", "stdio"),
    )
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run()
        return
    mcp.run(
        transport="streamable-http",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8021")),
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
