"""Persistencia en SQLite: estado de la mascota y recordatorios/eventos."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from platformdirs import user_data_dir

FMT = "%Y-%m-%dT%H:%M:%S"


def _iso(dt: datetime) -> str:
    return dt.strftime(FMT)


def default_db_path() -> Path:
    folder = Path(user_data_dir("buddy", appauthor=False, ensure_exists=True))
    return folder / "buddy.db"


class Storage:
    def __init__(self, path: str | os.PathLike | None = None):
        path = path or os.environ.get("BUDDY_DB") or default_db_path()
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_at TEXT NOT NULL,
                notify_at TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'recordatorio',
                notified INTEGER NOT NULL DEFAULT 0,
                uid TEXT UNIQUE
            );
            """
        )
        self.db.commit()

    # ---------------------------------------------------------------- mascota
    def save_pet(self, data: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv(key, value) VALUES('pet', ?)",
                        (json.dumps(data),))
        self.db.commit()

    def load_pet(self) -> dict | None:
        row = self.db.execute("SELECT value FROM kv WHERE key='pet'").fetchone()
        return json.loads(row["value"]) if row else None

    # ----------------------------------------------------------- recordatorios
    def add_reminder(self, title: str, due_at: datetime, kind: str = "recordatorio",
                     advance_min: int = 0, uid: str | None = None) -> int | None:
        """Crea un recordatorio/evento. Devuelve su id (None si el uid ya existía)."""
        notify_at = due_at - timedelta(minutes=advance_min)
        try:
            cur = self.db.execute(
                "INSERT INTO reminders(title, due_at, notify_at, kind, uid) VALUES(?,?,?,?,?)",
                (title, _iso(due_at), _iso(notify_at), kind, uid),
            )
        except sqlite3.IntegrityError:
            return None
        self.db.commit()
        return cur.lastrowid

    def due_reminders(self, now: datetime) -> list[sqlite3.Row]:
        """Pendientes de avisar (no más viejos de un día, para no avisar de cosas antiguas)."""
        return self.db.execute(
            "SELECT * FROM reminders WHERE notified=0 AND notify_at<=? AND due_at>=? "
            "ORDER BY due_at",
            (_iso(now), _iso(now - timedelta(days=1))),
        ).fetchall()

    def mark_notified(self, reminder_id: int) -> None:
        self.db.execute("UPDATE reminders SET notified=1 WHERE id=?", (reminder_id,))
        self.db.commit()

    def upcoming(self, now: datetime, limit: int = 10) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM reminders WHERE due_at>=? ORDER BY due_at LIMIT ?",
            (_iso(now), limit),
        ).fetchall()

    def delete_reminder(self, reminder_id: int) -> bool:
        cur = self.db.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
        self.db.commit()
        return cur.rowcount > 0

    @staticmethod
    def parse_due(row: sqlite3.Row) -> datetime:
        return datetime.strptime(row["due_at"], FMT)
