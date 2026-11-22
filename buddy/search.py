"""Búsqueda de archivos (por nombre y por contenido) y de programas instalados."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "site-packages", "AppData",
             "Library", "$RECYCLE.BIN"}
TEXT_EXT = {".txt", ".md", ".py", ".csv", ".json", ".html", ".tex", ".rst", ".log", ".java",
            ".js", ".c", ".cpp"}


def normalize(text: str) -> str:
    """Minúsculas y sin acentos, para comparar."""
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _norm_name(name: str) -> str:
    return re.sub(r"[_\-.]+", " ", normalize(name))


@dataclass
class Hit:
    name: str
    path: str       # ruta del archivo o comando/atajo del programa
    score: float
    how: str = "nombre"


def default_roots() -> list[Path]:
    home = Path.home()
    names = ["Documents", "Downloads", "Desktop", "Documentos", "Descargas", "Escritorio"]
    roots = [home / n for n in names if (home / n).is_dir()]
    return roots or [home]


def open_path(path: str) -> None:
    """Abre un archivo con el programa predeterminado del sistema."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


class FileIndex:
    def __init__(self, roots: list[Path] | None = None, max_files: int = 60000):
        self.roots = roots or default_roots()
        self.max_files = max_files
        self.entries: list[tuple[str, str]] = []   # (nombre, ruta)
        self._norms: list[str] = []
        self.ready = False

    def build_async(self) -> None:
        threading.Thread(target=self.build, daemon=True).start()

    def build(self) -> None:
        entries: list[tuple[str, str]] = []
        for root in self.roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
                for f in filenames:
                    if not f.startswith("."):
                        entries.append((f, os.path.join(dirpath, f)))
                if len(entries) >= self.max_files:
                    break
            if len(entries) >= self.max_files:
                break
        self._norms = [_norm_name(n) for n, _ in entries]
        self.entries = entries
        self.ready = True

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        q = _norm_name(query)
        hits: list[Hit] = []
        if self.entries and q:
            for _, score, idx in process.extract(q, self._norms, scorer=fuzz.WRatio,
                                                 limit=limit * 3, score_cutoff=65):
                name, path = self.entries[idx]
                hits.append(Hit(name, path, float(score)))
        hits = hits[:limit]
        if len([h for h in hits if h.score >= 75]) < 3:     # poca coincidencia: mira dentro
            seen = {h.path for h in hits}
            for h in self.search_content(query, limit=limit):
                if h.path not in seen and len(hits) < limit:
                    hits.append(h)
        return hits

    def search_content(self, query: str, limit: int = 5,
                       max_files: int = 800, max_bytes: int = 200_000) -> list[Hit]:
        words = [w for w in normalize(query).split() if len(w) > 2]
        if not words:
            return []
        hits, scanned = [], 0
        for name, path in self.entries:
            if Path(name).suffix.lower() not in TEXT_EXT:
                continue
            scanned += 1
            if scanned > max_files:
                break
            try:
                if os.path.getsize(path) > max_bytes:
                    continue
                text = normalize(Path(path).read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            if all(w in text for w in words):
                hits.append(Hit(name, path, 60.0, how="contenido"))
                if len(hits) >= limit:
                    break
        return hits


# Nombres comunes (en español) -> programa del sistema, para los que no aparecen en el menú de apps.
WIN_ALIASES = {
    "calculadora": "calc", "bloc de notas": "notepad", "paint": "mspaint",
    "explorador de archivos": "explorer", "explorador": "explorer",
    "administrador de tareas": "taskmgr", "simbolo del sistema": "cmd", "cmd": "cmd",
    "powershell": "powershell", "panel de control": "control",
    "configuracion": "ms-settings:", "recortes": "snippingtool",
}
MAC_ALIASES = {
    "calculadora": "/System/Applications/Calculator.app",
    "terminal": "/System/Applications/Utilities/Terminal.app",
    "configuracion del sistema": "/System/Applications/System Settings.app",
    "notas": "/System/Applications/Notes.app",
}
LINUX_ALIASES = {
    "calculadora": ("gnome-calculator", "kcalc", "mate-calc", "galculator"),
    "terminal": ("gnome-terminal", "konsole", "xfce4-terminal", "xterm"),
    "archivos": ("nautilus", "dolphin", "thunar", "nemo"),
    "bloc de notas": ("gedit", "kate", "mousepad", "xed"),
}


def _parse_start_apps(text: str) -> list[tuple[str, str]]:
    """Convierte la salida JSON de PowerShell `Get-StartApps` en (nombre, destino)."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for item in data if isinstance(data, list) else []:
        name, app_id = item.get("Name"), item.get("AppID")
        if name and app_id:
            out.append((name, "shell:AppsFolder\\" + app_id))
    return out


def _windows_start_apps() -> list[tuple[str, str]]:
    """Todas las apps del Menú Inicio de Windows, incluidas las de la Tienda (Calculadora, Fotos...)."""
    cmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return _parse_start_apps(res.stdout.decode("utf-8", errors="replace").strip().lstrip("\ufeff"))
    except (OSError, subprocess.SubprocessError):
        return []


def _merge_aliases(apps: dict[str, str], aliases: dict[str, str]) -> None:
    """Agrega los alias que no estén ya en la lista (comparando sin acentos ni mayúsculas)."""
    known = {normalize(n) for n in apps}
    for key, target in aliases.items():
        if key not in known:
            apps[key.capitalize()] = target


class AppIndex:
    """Programas instalados (Windows: Menú Inicio, macOS: .app, Linux: .desktop)."""

    def __init__(self):
        self.apps: list[tuple[str, str]] = []   # (nombre, destino)
        self._norms: list[str] = []
        self._loaded = False
        self._lock = threading.Lock()

    def build_async(self) -> None:
        """Carga la lista en segundo plano para que la primera búsqueda sea instantánea."""
        threading.Thread(target=self._ensure, daemon=True).start()

    def _ensure(self) -> None:
        with self._lock:
            if not self._loaded:
                self._load()

    def _load(self) -> None:
        apps: dict[str, str] = {}
        if sys.platform == "win32":
            for name, target in _windows_start_apps():
                apps.setdefault(name, target)
            dirs = [Path(os.environ.get("ProgramData", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
                    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
            for d in dirs:
                if d.is_dir():
                    for p in d.rglob("*.lnk"):
                        apps.setdefault(p.stem, str(p))
            _merge_aliases(apps, WIN_ALIASES)
        elif sys.platform == "darwin":
            for d in (Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications"):
                if d.is_dir():
                    for p in d.glob("*.app"):
                        apps.setdefault(p.stem, str(p))
            _merge_aliases(apps, {k: v for k, v in MAC_ALIASES.items() if Path(v).exists()})
        else:
            dirs = [Path("/usr/share/applications"), Path.home() / ".local/share/applications"]
            for d in dirs:
                if not d.is_dir():
                    continue
                for p in d.glob("*.desktop"):
                    name = exec_cmd = None
                    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.startswith("Name=") and name is None:
                            name = line[5:]
                        elif line.startswith("Exec=") and exec_cmd is None:
                            exec_cmd = re.sub(r"%[a-zA-Z]", "", line[5:]).strip()
                    if name and exec_cmd:
                        apps.setdefault(name, exec_cmd)
            found = {}
            for key, cmds in LINUX_ALIASES.items():
                path = next((shutil.which(c) for c in cmds if shutil.which(c)), None)
                if path:
                    found[key] = shlex.quote(path)
            _merge_aliases(apps, found)
        self.apps = sorted(apps.items())
        self._norms = [normalize(n) for n, _ in self.apps]
        self._loaded = True

    def search(self, query: str, limit: int = 3) -> list[Hit]:
        self._ensure()
        q = normalize(query)
        if not q or not self.apps:
            return []
        res = process.extract(q, self._norms, scorer=fuzz.WRatio, limit=limit * 3, score_cutoff=60)
        hits = [Hit(self.apps[i][0], self.apps[i][1], float(s), how="programa") for _, s, i in res]
        hits.sort(key=lambda h: (-h.score, len(h.name)))     # a igual puntaje, el nombre más corto
        return hits[:limit]

    @staticmethod
    def launch(hit: Hit) -> None:
        if sys.platform == "win32":
            os.startfile(hit.path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", hit.path])
        else:
            subprocess.Popen(shlex.split(hit.path), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
