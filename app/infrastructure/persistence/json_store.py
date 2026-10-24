"""Atomic JSON writes and the SQLite audit log."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.core.logging import request_id_var


def atomic_write_json(path: Path, payload: object, backup_directory: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup_directory is not None and path.is_file():
        backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_directory / f"{path.name}.{stamp}.json"
        backup.write_bytes(path.read_bytes())
        _trim_backups(backup_directory, path.name)
    temporary = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _trim_backups(directory: Path, name: str, keep: int = 20) -> None:
    matches = sorted(directory.glob(f"{name}.*.json"))
    for old in matches[:-keep]:
        old.unlink(missing_ok=True)


class AuditStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS camera_configuration_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    request_id TEXT,
                    success INTEGER NOT NULL,
                    requested_json TEXT NOT NULL,
                    previous_json TEXT,
                    confirmed_json TEXT,
                    error TEXT
                )
                """
            )

    def record(
        self,
        *,
        camera_id: str,
        success: bool,
        requested: dict,
        previous: dict | None,
        confirmed: dict | None,
        error: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO camera_configuration_events (
                    timestamp, camera_id, request_id, success, requested_json,
                    previous_json, confirmed_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    camera_id,
                    request_id_var.get(),
                    1 if success else 0,
                    json.dumps(requested),
                    json.dumps(previous) if previous is not None else None,
                    json.dumps(confirmed) if confirmed is not None else None,
                    error,
                ),
            )

    def list_events(self, *, limit: int, offset: int, camera_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM camera_configuration_events"
        parameters: list[object] = []
        if camera_id:
            query += " WHERE camera_id = ?"
            parameters.append(camera_id)
        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        parameters.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "camera_id": row["camera_id"],
                "request_id": row["request_id"],
                "success": bool(row["success"]),
                "requested": json.loads(row["requested_json"]),
                "previous": json.loads(row["previous_json"]) if row["previous_json"] else None,
                "confirmed": json.loads(row["confirmed_json"]) if row["confirmed_json"] else None,
                "error": row["error"],
            }
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection
