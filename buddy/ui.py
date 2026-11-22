"""Interfaz gráfica con Tkinter: la mascota animada, sus necesidades y el chat."""
from __future__ import annotations

import math
import queue
import random
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, ttk

import llm
from assistant import Assistant, Reply
from calendar_io import import_ics
from pet import LABELS, MIN_PLAY_ENERGY, STATS, Pet
from storage import Storage

TICK_MS = 1000     # lógica (necesidades, sueño, recordatorios)
FRAME_MS = 80      # animación

MOOD_COLORS = {
    "feliz": "#ffc9de", "normal": "#ffe3ee", "hambriento": "#ffe08a", "sucio": "#cdbb94",
    "aburrido": "#c9d4ff", "cansado": "#d2d2d2", "dormido": "#b3bfff",
}

LOW_MESSAGES = {
    "low:food": "Tengo hambre... ¿me das de comer?",
    "low:hygiene": "Estoy sucio, necesito un baño.",
    "low:fun": "Me aburro... ¿jugamos?",
    "low:energy": "Tengo mucho sueño...",
}


class BuddyApp(tk.Tk):
    def __init__(self, pet: Pet, storage: Storage, assistant: Assistant):
        super().__init__()
        self.pet, self.storage, self.assistant = pet, storage, assistant
        self.title(f"{pet.name} · tu asistente")
        self.geometry("420x660")
        self.minsize(380, 580)
        self.q: queue.Queue = queue.Queue()
        self.bubble_text, self.bubble_until = "", 0.0
        self._ticks = 0
        self._llm_busy = False
        self._stream_text = ""
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log(self.pet.name, "¡Hola! Puedes charlar conmigo de lo que quieras o escribir «ayuda» "
                                 "para ver lo que sé hacer.")
        self.after(300, self._tick)
        self.after(100, self._poll_queue)
        self.after(FRAME_MS, self._frame)

    # ------------------------------------------------------------- interfaz
    def _build_ui(self) -> None:
        self.canvas = tk.Canvas(self, width=280, height=240, bg="#f4f1fb", highlightthickness=0)
        self.canvas.pack(fill="x", padx=10, pady=(10, 4))

        bars = ttk.Frame(self)
        bars.pack(fill="x", padx=14)
        self.bars: dict[str, ttk.Progressbar] = {}
        for i, s in enumerate(STATS):
            ttk.Label(bars, text=LABELS[s], width=10).grid(row=i, column=0, sticky="w")
            pb = ttk.Progressbar(bars, maximum=100, length=250)
            pb.grid(row=i, column=1, sticky="ew", pady=1)
            self.bars[s] = pb
        bars.columnconfigure(1, weight=1)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=6)
        ttk.Button(btns, text="Alimentar", command=lambda: self._action(self.pet.feed)).pack(side="left", expand=True, fill="x")
        ttk.Button(btns, text="Bañar", command=lambda: self._action(self.pet.bathe)).pack(side="left", expand=True, fill="x")
        ttk.Button(btns, text="Jugar", command=self._open_game).pack(side="left", expand=True, fill="x")
        self.sleep_btn = ttk.Button(btns, text="Dormir", command=self._toggle_sleep)
        self.sleep_btn.pack(side="left", expand=True, fill="x")

        ttk.Button(self, text="Importar calendario (.ics)", command=self._import_ics).pack(fill="x", padx=10)

        self.chat = tk.Text(self, height=12, wrap="word", state="disabled", relief="flat", bg="#ffffff")
        self.chat.pack(fill="both", expand=True, padx=10, pady=8)
        self.chat.tag_configure("me", foreground="#1b4f9c", justify="right")
        self.chat.tag_configure("bot", foreground="#222222")

        row = ttk.Frame(self)
        row.pack(fill="x", padx=10, pady=(0, 10))
        self.entry = ttk.Entry(row)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self._send())
        ttk.Button(row, text="Enviar", command=self._send).pack(side="left", padx=(6, 0))
        self.entry.focus_set()

    def _log(self, who: str, text: str) -> None:
        self.chat.configure(state="normal")
        tag = "me" if who == "Tú" else "bot"
        self.chat.insert("end", f"{who}: {text}\n\n", tag)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def say(self, text: str, seconds: float = 6.0) -> None:
        self.bubble_text = text
        self.bubble_until = time.time() + seconds

    # ------------------------------------------------------------ acciones
    def _send(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._log("Tú", text)
        self._show(self.assistant.handle(text))

    def _show(self, reply: Reply) -> None:
        if reply.text:
            self._log(self.pet.name, reply.text)
            self.say(reply.text.split("\n")[0])
        if reply.game:
            self._open_game(announce=False)
        if reply.llm_prompt:
            if self._llm_busy:
                self._log(self.pet.name, "Espera un momento, sigo pensando en lo anterior...")
                return
            self._llm_busy = True
            summary, name, prompt = self.pet.summary(), self.pet.name, reply.llm_prompt
            threading.Thread(target=self._llm_worker, args=(prompt, summary, name), daemon=True).start()

    def _llm_worker(self, prompt: str, summary: str, name: str) -> None:
        """Corre en otro hilo: pide la respuesta a Ollama y la envía por trozos a la interfaz."""
        self.q.put(("begin", None))
        try:
            for piece in llm.stream(prompt, summary, name):
                self.q.put(("chunk", piece))
        finally:
            self.q.put(("end", None))

    def _poll_queue(self) -> None:
        try:
            while True:
                try:
                    kind, payload = self.q.get_nowait()
                except queue.Empty:
                    break
                if kind == "begin":
                    self._stream_text = ""
                    self._stream_write(f"{self.pet.name}: ")
                    self.say("Pensando...", seconds=60)
                elif kind == "chunk":
                    self._stream_text += payload
                    self._stream_write(payload)
                elif kind == "end":
                    self._stream_write("\n\n")
                    self._llm_busy = False
                    first = self._stream_text.strip().split("\n")[0]
                    self.say(first[:160] + ("..." if len(first) > 160 else ""), seconds=8)
        finally:
            self.after(100, self._poll_queue)

    def _stream_write(self, text: str) -> None:
        self.chat.configure(state="normal")
        self.chat.insert("end", text, "bot")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _action(self, fn) -> None:
        now = datetime.now()
        woke = self.pet.wake_up(now)
        ok, msg = fn(now)
        text = ("*bosteza* " if woke else "") + msg
        self._log(self.pet.name, text)
        self.say(msg)

    def _toggle_sleep(self) -> None:
        now = datetime.now()
        if self.pet.asleep:
            self.pet.wake_up(now)
            self._log(self.pet.name, "*bosteza* ¡Estoy despierto!")
        else:
            self._log(self.pet.name, self.pet.sleep_now(now)[1])

    def _import_ics(self) -> None:
        path = filedialog.askopenfilename(title="Elige tu calendario",
                                          filetypes=[("Calendario", "*.ics"), ("Todos", "*.*")])
        if not path:
            return
        try:
            added, skipped = import_ics(self.storage, path)
            self._log(self.pet.name, f"Importé {added} evento(s). Omití {skipped} (pasados o repetidos).")
        except Exception as exc:
            self._log(self.pet.name, f"No pude leer ese archivo: {exc}")

    def _open_game(self, announce: bool = True) -> None:
        now = datetime.now()
        if self.pet.wake_up(now):
            self._log(self.pet.name, "*bosteza* ¡Vale, vale, estoy despierto!")
        if self.pet.energy < MIN_PLAY_ENERGY:
            self._log(self.pet.name, f"{self.pet.name} está muy cansado para jugar. Déjalo descansar.")
            return
        RPSGame(self, self.pet.name, self._game_finished)

    def _game_finished(self, rounds: int) -> None:
        if rounds <= 0:
            self._log(self.pet.name, "¡Otra vez será!")
            return
        ok, msg = self.pet.play(datetime.now())
        self._log(self.pet.name, msg)
        self.say(msg)

    # ----------------------------------------------------- bucle de lógica
    def _tick(self) -> None:
        try:
            now = datetime.now()
            for ev in self.pet.update(now):
                self._on_pet_event(ev)
            for r in self.storage.due_reminders(now):
                self._notify(r, now)
            self._ticks += 1
            if self._ticks % 10 == 0:
                self.storage.save_pet(self.pet.to_dict())
        finally:
            self.after(TICK_MS, self._tick)

    def _on_pet_event(self, ev: str) -> None:
        if ev == "sleep:night":
            self._log(self.pet.name, "Tengo sueño... buenas noches. Zzz. (Escríbeme si me necesitas y me despierto.)")
        elif ev == "sleep:tired":
            self._log(self.pet.name, "Estoy agotado, me voy a dormir un rato. Zzz.")
        elif ev == "woke":
            self._log(self.pet.name, "¡Buenos días! Ya descansé. ¿Qué hacemos hoy?")
            self.say("¡Buenos días!")
        elif ev in LOW_MESSAGES:
            self._log(self.pet.name, LOW_MESSAGES[ev])
            self.say(LOW_MESSAGES[ev])

    def _notify(self, row, now: datetime) -> None:
        """Avisa de un recordatorio. Si la mascota duerme, se despierta para avisar."""
        if self.pet.wake_up(now):
            self._log(self.pet.name, "*bosteza* Perdón por despertarme... tengo algo que decirte.")
        due = Storage.parse_due(row)
        when = (f"empieza a las {due:%H:%M}" if due >= now
                else f"estaba programado para las {due:%H:%M}")
        text = f"⏰ {row['title']} ({when})"
        self._log(self.pet.name, text)
        self.say(text, seconds=15)
        self.storage.mark_notified(row["id"])
        self.bell()
        self.deiconify()
        self.lift()

    def _on_close(self) -> None:
        self.storage.save_pet(self.pet.to_dict())
        self.destroy()

    # ------------------------------------------------------------ animación
    def _frame(self) -> None:
        try:
            self._draw()
            for s in STATS:
                self.bars[s]["value"] = getattr(self.pet, s)
            self.sleep_btn.configure(text="Despertar" if self.pet.asleep else "Dormir")
        finally:
            self.after(FRAME_MS, self._frame)

    def _draw(self) -> None:
        c, p, t = self.canvas, self.pet, time.time()
        c.delete("all")
        mood = p.mood
        color = MOOD_COLORS.get(mood, "#ffe3ee")
        bounce = 0 if p.asleep else math.sin(t * 3) * 4
        cx, cy = 140, 140 + bounce
        line = "#7a5c70"

        # orejas y cuerpo
        for dx in (-30, 30):
            c.create_oval(cx + dx - 16, cy - 105, cx + dx + 16, cy - 35, fill=color, outline=line, width=2)
        c.create_oval(cx - 70, cy - 70, cx + 70, cy + 60, fill=color, outline=line, width=2)

        # ojos
        if p.asleep or (t % 4) < 0.15:
            for dx in (-28, 28):
                c.create_line(cx + dx - 9, cy - 15, cx + dx + 9, cy - 15, width=3, fill=line)
        else:
            for dx in (-28, 28):
                c.create_oval(cx + dx - 8, cy - 25, cx + dx + 8, cy - 5, fill="white", outline=line, width=2)
                c.create_oval(cx + dx - 3, cy - 19, cx + dx + 3, cy - 11, fill=line, outline=line)

        # boca según el ánimo
        if p.asleep:
            c.create_oval(cx - 5, cy + 12, cx + 5, cy + 20, outline=line, width=2)
        elif mood == "feliz":
            c.create_arc(cx - 22, cy - 2, cx + 22, cy + 34, start=200, extent=140, style="arc", outline=line, width=3)
        elif mood == "normal":
            c.create_line(cx - 12, cy + 18, cx + 12, cy + 18, width=3, fill=line)
        else:
            c.create_arc(cx - 20, cy + 16, cx + 20, cy + 46, start=20, extent=140, style="arc", outline=line, width=3)

        # suciedad
        if p.hygiene < 35 and not p.asleep:
            for ox, oy in ((-45, 20), (40, 30), (-10, 45), (50, -20)):
                c.create_oval(cx + ox - 4, cy + oy - 4, cx + ox + 4, cy + oy + 4, fill="#7b5a3a", outline="")

        # Zzz mientras duerme
        if p.asleep:
            for i, ch in enumerate("zZZ"):
                off = (t * 12 + i * 18) % 54
                c.create_text(cx + 70 + i * 12, cy - 60 - off, text=ch, font=("Arial", 12 + i * 4, "bold"), fill="#5a67c9")

        c.create_text(140, 228, text=f"{p.name} · {mood}", font=("Arial", 11, "bold"), fill=line)

        # globo de diálogo
        if time.time() < self.bubble_until and self.bubble_text:
            item = c.create_text(10, 10, text=self.bubble_text, anchor="nw", width=250,
                                 font=("Arial", 10), fill="#222222")
            x1, y1, x2, y2 = c.bbox(item)
            bg = c.create_rectangle(x1 - 6, y1 - 4, x2 + 6, y2 + 4, fill="#ffffff", outline=line)
            c.tag_lower(bg, item)


class RPSGame(tk.Toplevel):
    """Minijuego de piedra, papel o tijera contra la mascota."""

    OPTIONS = ("Piedra", "Papel", "Tijera")
    BEATS = {"Piedra": "Tijera", "Papel": "Piedra", "Tijera": "Papel"}

    def __init__(self, master, pet_name: str, on_finish):
        super().__init__(master)
        self.title(f"Jugar con {pet_name}")
        self.resizable(False, False)
        self.pet_name, self.on_finish = pet_name, on_finish
        self.rounds = self.wins = self.losses = 0
        self.info = ttk.Label(self, text="¡Elige!", font=("Arial", 12), padding=12, justify="center")
        self.info.pack()
        row = ttk.Frame(self)
        row.pack(padx=12, pady=4)
        for opt in self.OPTIONS:
            ttk.Button(row, text=opt, command=lambda o=opt: self._play(o)).pack(side="left", padx=4)
        ttk.Button(self, text="Terminar", command=self._finish).pack(pady=10)
        self.protocol("WM_DELETE_WINDOW", self._finish)

    def _play(self, choice: str) -> None:
        mine = random.choice(self.OPTIONS)
        self.rounds += 1
        if mine == choice:
            res = "Empate"
        elif self.BEATS[choice] == mine:
            res, self.wins = "¡Ganaste!", self.wins + 1
        else:
            res, self.losses = f"¡Gana {self.pet_name}!", self.losses + 1
        self.info.configure(text=f"{self.pet_name} eligió {mine}.\n{res}\n\nGanadas {self.wins} · Perdidas {self.losses}")

    def _finish(self) -> None:
        self.destroy()
        self.on_finish(self.rounds)
