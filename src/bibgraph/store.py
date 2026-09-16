"""Transactional run state: fetch attempts, artifact ledger, review state.

SQLite holds run state and caches. The deterministic JSON/JSONL exports under
data/ are what gets versioned and diffed; this database is machine-local.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
create table if not exists artifact (
    asset_id       text primary key,
    work_id        text not null,
    alias          text not null,
    role           text not null,
    intent         text not null,
    requested_url  text not null,
    final_url      text,
    status         text not null,          -- downloaded|metadata_only|manual_required|failed|not_requested
    http_status    integer,
    media_type     text,
    bytes          integer,
    sha256         text,
    path           text,
    etag           text,
    last_modified  text,
    attempts       integer not null default 0,
    reason         text,
    fetched_at     text
);

create table if not exists attempt (
    id             integer primary key autoincrement,
    run_id         text not null,
    asset_id       text not null,
    started_at     text not null,
    outcome        text not null,
    http_status    integer,
    detail         text
);

create table if not exists http_cache (
    url            text primary key,
    fetched_at     text not null,
    expires_at     text,
    status         integer,
    body_path      text,
    etag           text,
    last_modified  text
);

create table if not exists review (
    work_id        text primary key,
    pass_status    text not null default 'unread',
    payload        text not null default '{}',
    updated_at     text
);

create index if not exists attempt_asset on attempt(asset_id);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("pragma foreign_keys=on")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- artifacts ---------------------------------------------------------

    def record_artifact(self, row: dict[str, Any]) -> None:
        columns = [
            "asset_id", "work_id", "alias", "role", "intent", "requested_url",
            "final_url", "status", "http_status", "media_type", "bytes", "sha256",
            "path", "etag", "last_modified", "attempts", "reason", "fetched_at",
        ]
        values = [row.get(c) for c in columns]
        placeholders = ",".join("?" * len(columns))
        self.connection.execute(
            f"insert or replace into artifact ({','.join(columns)}) values ({placeholders})",
            values,
        )
        self.connection.commit()

    def get_artifact(self, asset_id: str) -> dict | None:
        cursor = self.connection.execute(
            "select * from artifact where asset_id = ?", (asset_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def artifacts(self) -> list[dict]:
        cursor = self.connection.execute("select * from artifact order by alias, role")
        return [dict(r) for r in cursor.fetchall()]

    def log_attempt(self, run_id: str, asset_id: str, started_at: str,
                    outcome: str, http_status: int | None, detail: str | None) -> None:
        self.connection.execute(
            "insert into attempt (run_id, asset_id, started_at, outcome, http_status, detail)"
            " values (?,?,?,?,?,?)",
            (run_id, asset_id, started_at, outcome, http_status, detail),
        )
        self.connection.commit()

    def attempt_count(self, asset_id: str) -> int:
        cursor = self.connection.execute(
            "select count(*) as n from attempt where asset_id = ?", (asset_id,))
        return int(cursor.fetchone()["n"])

    # -- robots / http cache ----------------------------------------------

    def cache_get(self, url: str) -> dict | None:
        cursor = self.connection.execute("select * from http_cache where url = ?", (url,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def cache_put(self, url: str, **fields: Any) -> None:
        existing = self.cache_get(url) or {"url": url}
        existing.update(fields)
        existing["url"] = url
        columns = ["url", "fetched_at", "expires_at", "status", "body_path",
                   "etag", "last_modified"]
        self.connection.execute(
            f"insert or replace into http_cache ({','.join(columns)}) "
            f"values ({','.join('?' * len(columns))})",
            [existing.get(c) for c in columns],
        )
        self.connection.commit()

    # -- review ------------------------------------------------------------

    def set_review(self, work_id: str, pass_status: str, payload: dict, updated_at: str) -> None:
        self.connection.execute(
            "insert or replace into review (work_id, pass_status, payload, updated_at)"
            " values (?,?,?,?)",
            (work_id, pass_status, json.dumps(payload, sort_keys=True), updated_at),
        )
        self.connection.commit()

    def reviews(self) -> dict[str, dict]:
        cursor = self.connection.execute("select * from review")
        out = {}
        for row in cursor.fetchall():
            out[row["work_id"]] = {
                "pass_status": row["pass_status"],
                "payload": json.loads(row["payload"]),
                "updated_at": row["updated_at"],
            }
        return out


@contextmanager
def open_store(path: Path) -> Iterator[Store]:
    store = Store(path)
    try:
        yield store
    finally:
        store.close()
