"""Cerebro del asistente: entiende lo que escribe el usuario y ejecuta la acción.

Entiende el lenguaje con reglas (expresiones regulares + dateparser para las fechas),
así funciona sin internet. Si hay un modelo de lenguaje configurado (llm.py), las frases
que no encajan en ninguna regla se le delegan para conversar.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime

import llm
from pet import Pet
from search import AppIndex, FileIndex, Hit, normalize, open_path
from storage import Storage

DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

WAKE_LINES = ["*bosteza*", "*se estira*", "*abre un ojo*", "*se frota los ojos*"]

STOPWORDS = {
    "busca", "buscame", "buscar", "encuentra", "encuentrame", "localiza", "donde", "esta",
    "queda", "abre", "abreme", "abrir", "inicia", "iniciar", "ejecuta", "lanza", "lanzar",
    "corre", "el", "la", "los", "las", "un", "una", "mi", "mis", "archivo", "archivos",
    "documento", "documentos", "programa", "programas", "aplicacion", "app", "de", "del",
    "que", "se", "llama", "llamado", "llamada", "por", "favor", "en", "computador",
    "computadora", "pc", "sobre", "con", "para", "me", "puedes", "podrias", "guarde",
}

HELP = (
    "Puedo ayudarte con esto:\n"
    "• Recordatorios: «recuérdame mañana a las 3 pm estudiar IA»\n"
    "• Agenda: «qué tengo hoy», «mis eventos», «borra el recordatorio 2»\n"
    "• Archivos: «busca el informe de redes», «abre el documento de contabilidad»\n"
    "• Programas: «abre chrome», «abre la calculadora»\n"
    "• Cuidarme: «dame de comer», «báñate», «juguemos», «duérmete», «despierta»\n"
    "• Para importar tu calendario usa el botón «Importar .ics»."
)


@dataclass
class Reply:
    text: str
    game: bool = False                 # la interfaz debe abrir el minijuego
    llm_prompt: str | None = None      # la interfaz debe pedir la respuesta al modelo


def fmt_dt(dt: datetime, now: datetime) -> str:
    days = (dt.date() - now.date()).days
    hora = dt.strftime("%H:%M")
    if days == 0:
        return f"hoy a las {hora}"
    if days == 1:
        return f"mañana a las {hora}"
    return f"{DAYS[dt.weekday()]} {dt.day:02d}/{dt.month:02d} a las {hora}"


def clean_query(n: str) -> str:
    words = [w for w in re.findall(r"[\w.]+", n) if w not in STOPWORDS]
    return " ".join(words)


class Assistant:
    def __init__(self, pet: Pet, storage: Storage, files: FileIndex, apps: AppIndex):
        self.pet = pet
        self.storage = storage
        self.files = files
        self.apps = apps
        self.last_results: list[str] = []

    # ------------------------------------------------------------ entrada
    def handle(self, text: str, now: datetime | None = None) -> Reply:
        now = now or datetime.now()
        text = text.strip()
        if not text:
            return Reply("Dime algo, te escucho.")
        n = normalize(text)
        self.pet.touch(now)

        m = re.search(r"(?:te llamas|tu nombre es|ll[aá]mate)\s+(\w+)", text, re.I)
        if m:
            self.pet.name = m.group(1).capitalize()
            return Reply(f"¡Me encanta! Desde ahora me llamo {self.pet.name}.")

        # Mandarlo a dormir no debe despertarlo primero.
        if re.search(r"\b(duerme|duermete|a dormir|a la cama|siesta|buenas noches)\b", n):
            return Reply(self.pet.sleep_now(now)[1])

        # Cualquier otra petición despierta a la mascota para ayudar.
        pre = ""
        if self.pet.asleep:
            self.pet.wake_up(now)
            pre = random.choice(WAKE_LINES) + " "

        def say(msg: str, **kw) -> Reply:
            return Reply(pre + msg, **kw)

        if re.search(r"\b(despierta|despiertate|levantate)\b", n):
            return say("Ya estoy despierto, ¿en qué te ayudo?" if not pre else "¿Qué necesitas?")

        # Abrir un resultado de la última búsqueda: «abre el 2» o solo «2»
        m = re.fullmatch(r"(?:abre|abrir|abrelo|el|numero)?\s*(\d)", n)
        if m and self.last_results:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(self.last_results):
                open_path(self.last_results[idx])
                return say("Abriendo el archivo.")

        m = re.search(r"\b(borra|borrar|elimina|eliminar|quita|cancela)\b.*?(\d+)", n)
        if m:
            ok = self.storage.delete_reminder(int(m.group(2)))
            return say("Listo, lo borré." if ok else "No encontré ese recordatorio.")

        if re.search(r"(que tengo|mis (recordatorios|eventos|pendientes)|mi agenda|"
                     r"mi calendario|proximos eventos|que hay (hoy|manana))", n):
            return say(self._list_reminders(now))

        if re.search(r"\b(recuerdame|recuerda me|recordame|agendame|agenda|"
                     r"crea(me)? (un |el )?(recordatorio|evento)|"
                     r"programa (un )?(recordatorio|evento)|ponme (un |una )?(recordatorio|alarma))\b", n):
            return say(self._create_reminder(text, n, now))

        if re.search(r"\b(busca|buscame|buscar|encuentra|encuentrame|localiza|donde esta|donde queda)\b", n):
            if re.search(r"\b(programa|aplicacion|app)\b", n):
                return say(self._open_app(n, fallback_files=False))
            return say(self._find_files(n, open_best=False))

        if re.search(r"\b(abre|abreme|abrir|inicia|iniciar|ejecuta|lanza|lanzar|corre|arranca|prende)\b", n):
            if re.search(r"\b(archivo|documento|pdf|foto|imagen|presentacion|informe)\b|\w\.\w{2,4}\b", n):
                return say(self._find_files(n, open_best=True))
            return say(self._open_app(n, fallback_files=True))

        if re.search(r"\b(aliment\w*|dale de comer|dar de comer|dame de comer|dale comida|a comer|comida)\b", n):
            return say(self.pet.feed(now)[1])
        if re.search(r"\b(bana\w*|banar\w*|banate|bano|ducha\w*|lavate|aseate)\b", n):
            return say(self.pet.bathe(now)[1])
        if re.search(r"\b(jug\w*|jueg\w*|divert\w*)\b", n):
            if self.pet.energy < 15:
                return say(f"{self.pet.name} está muy cansado para jugar. Déjalo descansar.")
            return say(f"¡Sí! Juguemos a piedra, papel o tijera.", game=True)

        if re.search(r"\b(como estas|como te sientes|como andas|estado|que tal)\b", n):
            return say(self.pet.summary())
        if re.search(r"\b(ayuda|que puedes hacer|que sabes hacer|comandos)\b", n):
            return say(HELP)
        if re.search(r"\b(hola|buenas|buenos dias|buenas tardes|hey)\b", n):
            return say(f"¡Hola! Soy {self.pet.name}. ¿En qué te ayudo? (escribe «ayuda» para ver qué sé hacer)")
        if re.search(r"\b(gracias|genial|excelente)\b", n):
            return say("¡De nada! Para eso estoy ♥")

        # Todo lo demás es conversación libre: se lo pasamos al modelo local (Ollama).
        model, error = llm.status()
        if model:
            return Reply(pre.strip(), llm_prompt=text)
        return say(f"Para charlar de cualquier tema necesito un modelo local. {error}\n"
                   "Mientras tanto escribe «ayuda» para ver lo que puedo hacer sin él.")

    # --------------------------------------------------------- recordatorios
    def _create_reminder(self, original: str, n: str, now: datetime) -> str:
        import dateparser.search  # se importa aquí porque tarda un poco en cargar

        try:
            found = dateparser.search.search_dates(
                original, languages=["es"],
                settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": now,
                          "RETURN_AS_TIMEZONE_AWARE": False},
            )
        except Exception:
            found = None
        if not found:
            return ("¿Para cuándo? Dímelo así: «recuérdame mañana a las 3 pm estudiar IA» "
                    "o «recuérdame en 2 horas llamar a mamá».")

        matched, due = max(found, key=lambda x: len(x[0]))
        if not re.search(r"\d|hora|minuto|mediodia|medianoche", normalize(matched)):
            due = due.replace(hour=9, minute=0, second=0)    # sin hora: a las 9 am
        due = due.replace(second=0, microsecond=0)
        if due <= now:
            return "Esa fecha ya pasó. ¿Me la das en el futuro?"

        title = original.replace(matched, " ")
        title = re.sub(r"(?i)\b(recu[eé]rdame|recordame|ag[eé]ndame|agenda|crea(me)?( un| el)?"
                       r"( recordatorio| evento)?|programa( un)?|ponme( un| una)?|recordatorio|"
                       r"evento|alarma)\b", " ", title)
        title = re.sub(r"\s+", " ", title).strip(" ,.;:")
        while True:
            new = re.sub(r"(?i)^(que|de|para|a|el|la|mi|en|y)\s+|\s+(que|de|para|a|el|la|mi|en|y)$",
                         "", title)
            if new == title:
                break
            title = new
        title = title[:1].upper() + title[1:] if title else "Recordatorio"

        is_event = bool(re.search(r"\b(reunion|cita|clase|examen|evento|entrega|parcial)\b", n))
        advance = 15 if is_event and (due - now).total_seconds() > 15 * 60 else 0
        rid = self.storage.add_reminder(title, due, "evento" if is_event else "recordatorio", advance)
        extra = f" (te aviso {advance} min antes)" if advance else ""
        return f"Listo, anotado: «{title}» {fmt_dt(due, now)}{extra}. [id {rid}]"

    def _list_reminders(self, now: datetime) -> str:
        rows = self.storage.upcoming(now, 10)
        if not rows:
            return "No tienes nada pendiente. ¡Día libre!"
        lines = [f"• [{r['id']}] {fmt_dt(Storage.parse_due(r), now)}: {r['title']}"
                 + (" (evento)" if r["kind"] == "evento" else "") for r in rows]
        return "Esto es lo que viene:\n" + "\n".join(lines)

    # ------------------------------------------------- archivos y programas
    def _find_files(self, n: str, open_best: bool) -> str:
        q = clean_query(n)
        if not q:
            return "¿Qué archivo buscas? Dime el nombre o de qué trata."
        hits = self.files.search(q)
        note = "" if self.files.ready else "\n(Aún estoy indexando tus carpetas, puede faltar algo.)"
        if not hits:
            return f"No encontré nada parecido a «{q}».{note}"
        self.last_results = [h.path for h in hits]
        best = hits[0]
        if open_best and best.how == "nombre" and (best.score >= 88 or len(hits) == 1):
            open_path(best.path)
            return f"Abriendo «{best.name}»."
        lines = [f"{i}. {h.name}  ({h.how}) — {self._short_dir(h)}" for i, h in enumerate(hits, 1)]
        return "Encontré esto (escribe el número para abrirlo):\n" + "\n".join(lines) + note

    @staticmethod
    def _short_dir(hit: Hit) -> str:
        parts = hit.path.replace("\\", "/").split("/")[:-1]
        return "/".join(parts[-2:])

    def _open_app(self, n: str, fallback_files: bool) -> str:
        q = clean_query(n)
        if not q:
            return "¿Qué programa quieres abrir?"
        hits = self.apps.search(q)
        if hits and hits[0].score >= 75:
            try:
                AppIndex.launch(hits[0])
            except OSError as exc:
                return f"No pude abrir {hits[0].name}: {exc}"
            return f"Abriendo {hits[0].name}."
        if fallback_files:
            res = self._find_files(n, open_best=True)
            if not res.startswith("No encontré"):
                return res
        if hits:
            return "No estoy seguro. ¿Quisiste decir: " + ", ".join(h.name for h in hits) + "?"
        return f"No encontré ningún programa llamado «{q}»."
