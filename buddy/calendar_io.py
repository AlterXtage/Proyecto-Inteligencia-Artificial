"""Importar eventos desde un archivo .ics (Google Calendar, Outlook, Apple Calendar).

Limitación: los eventos repetitivos (RRULE) solo se importan en su primera fecha.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from storage import Storage


def _unescape(value: str) -> str:
    return (value.replace("\\n", " ").replace("\\N", " ")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def _parse_dt(value: str) -> datetime | None:
    value = value.strip()
    try:
        if len(value) == 8:                               # evento de día completo
            return datetime.strptime(value, "%Y%m%d").replace(hour=9)
        if value.endswith("Z"):                           # UTC -> hora local
            dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return dt.astimezone().replace(tzinfo=None)
        return datetime.strptime(value, "%Y%m%dT%H%M%S")  # hora local / con TZID
    except ValueError:
        return None


def parse_ics(text: str) -> list[dict]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:              # línea continuada
            lines[-1] += raw[1:]
        else:
            lines.append(raw)

    events, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur and cur.get("start"):
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, _, val = line.partition(":")
            name = key.split(";")[0].upper()
            if name == "DTSTART":
                cur["start"] = _parse_dt(val)
            elif name == "SUMMARY":
                cur["title"] = _unescape(val)
            elif name == "UID":
                cur["uid"] = val.strip()
    return events


def import_ics(storage: Storage, path: str | Path, now: datetime | None = None) -> tuple[int, int]:
    """Importa eventos futuros. Devuelve (agregados, omitidos)."""
    now = now or datetime.now()
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    added = skipped = 0
    for ev in parse_ics(text):
        start = ev["start"]
        if start < now:
            skipped += 1
            continue
        advance = 15 if (start - now).total_seconds() > 15 * 60 else 0
        rid = storage.add_reminder(ev.get("title", "Evento"), start, kind="evento",
                                   advance_min=advance, uid=ev.get("uid"))
        if rid is None:
            skipped += 1
        else:
            added += 1
    return added, skipped
