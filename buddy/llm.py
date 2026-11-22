"""Conversación libre con un modelo de lenguaje LOCAL, usando Ollama.

Todo corre en tu computador: no se envía nada a internet. Necesitas:
  1. Instalar Ollama (https://ollama.com) y dejarlo abierto.
  2. Descargar un modelo una sola vez, por ejemplo:  ollama pull llama3.2

Variables de entorno opcionales:
  BUDDY_MODEL   modelo a usar (por defecto "llama3.2")
  OLLAMA_HOST   dirección del servidor (por defecto http://127.0.0.1:11434)

La mascota recuerda los últimos turnos de la conversación, y el modelo conoce
el estado actual de la mascota (hambre, sueño...) para responder con personalidad.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Iterator

MODEL = os.environ.get("BUDDY_MODEL", "llama3.2")
HISTORY_TURNS = 8        # cuántos intercambios (usuario + respuesta) recuerda
CHECK_TTL = 20.0         # segundos que se recuerda si Ollama estaba disponible

DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

SYSTEM = (
    "Eres {name}, una mascota virtual simpática y cariñosa que vive en el computador de tu "
    "dueño. Además de ser su mascota, eres un asistente de IA general: puedes conversar de "
    "cualquier tema, explicar cosas, ayudar con tareas, programación y estudio. "
    "Responde siempre en español, de forma clara y natural. Sé breve en la charla casual y "
    "detallado cuando te pidan explicaciones o ayuda técnica. Deja ver tu personalidad según "
    "tu estado actual, sin exagerar y sin dejar de ser útil. "
    "Si te piden crear recordatorios, buscar archivos o abrir programas, indícales las frases "
    "que entiendes, por ejemplo «recuérdame mañana a las 3 pm estudiar» o «busca el informe». "
    "No inventes datos sobre su calendario ni sus archivos.\n"
    "Fecha y hora actuales: {now}.\n"
    "Tu estado actual: {summary}"
)

_lock = threading.Lock()
_history: deque = deque(maxlen=HISTORY_TURNS * 2)
_cache: dict = {"t": 0.0, "model": None, "error": None}


def _client(timeout: float | None):
    import ollama

    return ollama.Client(timeout=timeout)


def _installed(client) -> list[str]:
    names = []
    for m in client.list().models:
        n = getattr(m, "model", None)
        if n is None and hasattr(m, "get"):
            n = m.get("model") or m.get("name")
        if n:
            names.append(n)
    return names


def _pick(names: list[str]) -> str | None:
    """Elige el modelo configurado si está instalado; si no, el primero que sirva para chat."""
    if MODEL in names:
        return MODEL
    if ":" not in MODEL:
        for n in names:
            if n.split(":")[0] == MODEL:
                return n
    for n in names:
        if "embed" not in n.lower():
            return n
    return None


def status(force: bool = False) -> tuple[str | None, str | None]:
    """Devuelve (modelo, error). Si hay modelo, error es None. El resultado se guarda unos segundos."""
    now = time.time()
    if not force and now - _cache["t"] < CHECK_TTL:
        return _cache["model"], _cache["error"]
    model = error = None
    try:
        names = _installed(_client(2.0))
        model = _pick(names)
        if model is None:
            error = f"Ollama no tiene ningún modelo instalado. Descarga uno con:  ollama pull {MODEL}"
    except ImportError:
        error = "Falta la librería de Ollama. Ejecuta:  uv sync"
    except Exception:
        error = "No encuentro Ollama. Instálalo desde https://ollama.com y déjalo abierto."
    _cache.update(t=now, model=model, error=error)
    return model, error


def available() -> bool:
    return status()[0] is not None


def reset() -> None:
    """Olvida la conversación."""
    with _lock:
        _history.clear()


def stream(text: str, summary: str, name: str) -> Iterator[str]:
    """Genera la respuesta por trozos, a medida que el modelo la va escribiendo."""
    model, error = status()
    if model is None:
        yield error or "No pude conectar con Ollama."
        return

    d = datetime.now()
    now = f"{DAYS[d.weekday()]} {d:%d/%m/%Y %H:%M}"
    messages = [{"role": "system",
                 "content": SYSTEM.format(name=name, summary=summary, now=now)}]
    with _lock:
        messages += list(_history)
    messages.append({"role": "user", "content": text})

    pieces: list[str] = []
    try:
        for chunk in _client(180.0).chat(model=model, messages=messages, stream=True):
            piece = chunk["message"]["content"]
            if piece:
                pieces.append(piece)
                yield piece
    except Exception as exc:
        _cache["t"] = 0.0          # vuelve a comprobar la conexión la próxima vez
        yield f"\n(Ollama dejó de responder: {type(exc).__name__})"
        return

    with _lock:
        _history.append({"role": "user", "content": text})
        _history.append({"role": "assistant", "content": "".join(pieces)})


def chat(text: str, summary: str, name: str) -> str:
    """Versión sin transmisión: devuelve la respuesta completa."""
    return "".join(stream(text, summary, name)).strip() or "..."
