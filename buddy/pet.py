"""Lógica de la mascota: necesidades, estados de ánimo y ciclo de sueño.

No depende de librerías externas ni de la interfaz, así se puede probar sola.
Todas las necesidades van de 0 (mal) a 100 (perfecto).
"""
from __future__ import annotations

from datetime import datetime, timedelta

STATS = ("food", "hygiene", "fun", "energy")
LABELS = {"food": "Comida", "hygiene": "Higiene", "fun": "Diversión", "energy": "Energía"}

# Puntos que baja cada necesidad por minuto real. Negativo = se recupera.
AWAKE_RATES = {"food": 0.5, "hygiene": 0.3, "fun": 0.4, "energy": 0.2}
ASLEEP_RATES = {"food": 0.1, "hygiene": 0.05, "fun": 0.05, "energy": -0.8}

LOW = 20                  # por debajo de esto la mascota se queja
MIN_PLAY_ENERGY = 15      # con menos energía no quiere jugar
MAX_CATCHUP_MIN = 12 * 60  # máximo de tiempo que se simula al reabrir la app


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _parse_dt(value, default: datetime) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return default


class Pet:
    """Mascota con necesidades que cambian con el tiempo y un ciclo de sueño.

    Estados de sueño:
      - "night": duerme por la hora (entre sleep_start y sleep_end).
      - "tired": se quedó sin energía.
      - "nap":   el usuario la mandó a dormir.
    Si el usuario la despierta durante su horario de sueño, queda despierta
    (awake_override) hasta que pasen `override_minutes` sin interacción.
    """

    def __init__(self, name: str = "Buddy", sleep_start: int = 23, sleep_end: int = 6,
                 override_minutes: int = 10, now: datetime | None = None):
        now = now or datetime.now()
        self.name = name
        self.sleep_start = sleep_start
        self.sleep_end = sleep_end
        self.override_minutes = override_minutes
        self.food = 80.0
        self.hygiene = 80.0
        self.fun = 80.0
        self.energy = 100.0
        self.asleep = False
        self.sleep_reason: str | None = None
        self.awake_override = False
        self.last_tick = now
        self.last_interaction = now

    # ------------------------------------------------------------------ tiempo
    def is_sleep_hour(self, t: datetime) -> bool:
        h = t.hour
        if self.sleep_start > self.sleep_end:      # ej. 23 -> 6 (cruza medianoche)
            return h >= self.sleep_start or h < self.sleep_end
        return self.sleep_start <= h < self.sleep_end

    def touch(self, now: datetime | None = None) -> None:
        self.last_interaction = now or datetime.now()

    def update(self, now: datetime | None = None) -> list[str]:
        """Avanza el tiempo hasta `now`. Devuelve eventos: 'sleep:night', 'woke', 'low:food'..."""
        now = now or datetime.now()
        events: list[str] = []
        elapsed = (now - self.last_tick).total_seconds() / 60
        if elapsed <= 0:
            self.last_tick = now
            return events
        elapsed = min(elapsed, MAX_CATCHUP_MIN)
        t = now - timedelta(minutes=elapsed)
        remaining = elapsed
        while remaining > 1e-9:
            chunk = min(remaining, 5.0)
            t += timedelta(minutes=chunk)
            events += self._decay(chunk)
            events += self._update_sleep(t)
            remaining -= chunk
        self.last_tick = now
        return events

    def _decay(self, minutes: float) -> list[str]:
        rates = ASLEEP_RATES if self.asleep else AWAKE_RATES
        events = []
        for s in STATS:
            old = getattr(self, s)
            new = _clamp(old - rates[s] * minutes)
            setattr(self, s, new)
            if not self.asleep and old >= LOW > new:
                events.append(f"low:{s}")
        return events

    def _update_sleep(self, t: datetime) -> list[str]:
        sleep_time = self.is_sleep_hour(t)
        idle = (t - self.last_interaction).total_seconds() / 60
        if self.awake_override and idle >= self.override_minutes:
            self.awake_override = False

        if self.asleep:
            if sleep_time:
                self.sleep_reason = "night"
            wake = (
                (self.sleep_reason == "night" and not sleep_time and self.energy >= 60)
                or (self.sleep_reason == "tired" and self.energy >= 60)
                or (self.sleep_reason == "nap" and self.energy >= 90)
            )
            if wake:
                self.asleep = False
                self.sleep_reason = None
                return ["woke"]
            return []

        if self.energy <= 5 and not self.awake_override:
            self.asleep, self.sleep_reason = True, "tired"
            return ["sleep:tired"]
        if sleep_time and not self.awake_override:
            self.asleep, self.sleep_reason = True, "night"
            return ["sleep:night"]
        return []

    # ----------------------------------------------------------------- sueño
    def wake_up(self, now: datetime | None = None) -> bool:
        """El usuario (o un recordatorio) despierta a la mascota. True si estaba dormida."""
        now = now or datetime.now()
        self.touch(now)
        if not self.asleep:
            return False
        self.asleep = False
        self.sleep_reason = None
        self.awake_override = True
        return True

    def sleep_now(self, now: datetime | None = None) -> tuple[bool, str]:
        self.touch(now)
        if self.asleep:
            return False, f"{self.name} ya está dormido."
        if self.energy >= 85:
            return False, f"{self.name} no tiene sueño todavía."
        self.asleep, self.sleep_reason, self.awake_override = True, "nap", False
        return True, f"{self.name} se acurruca y se queda dormido. Zzz..."

    # -------------------------------------------------------------- acciones
    def feed(self, now: datetime | None = None) -> tuple[bool, str]:
        self.touch(now)
        if self.asleep:
            return False, "Zzz..."
        if self.food >= 95:
            return False, f"{self.name} está lleno, ya no quiere más."
        self.food = _clamp(self.food + 35)
        return True, f"¡Ñam ñam! {self.name} comió con ganas."

    def bathe(self, now: datetime | None = None) -> tuple[bool, str]:
        self.touch(now)
        if self.asleep:
            return False, "Zzz..."
        if self.hygiene >= 95:
            return False, f"{self.name} ya está limpio y brillante."
        self.hygiene = _clamp(self.hygiene + 50)
        self.fun = _clamp(self.fun - 5)
        return True, f"¡Splash! {self.name} quedó limpio y huele rico."

    def play(self, now: datetime | None = None) -> tuple[bool, str]:
        self.touch(now)
        if self.asleep:
            return False, "Zzz..."
        if self.energy < MIN_PLAY_ENERGY:
            return False, f"{self.name} está muy cansado para jugar. Déjalo descansar."
        self.fun = _clamp(self.fun + 30)
        self.energy = _clamp(self.energy - 10)
        self.hygiene = _clamp(self.hygiene - 5)
        self.food = _clamp(self.food - 5)
        return True, f"¡{self.name} se divirtió muchísimo! ♥"

    # ---------------------------------------------------------------- estado
    @property
    def mood(self) -> str:
        if self.asleep:
            return "dormido"
        worst = min(STATS, key=lambda s: getattr(self, s))
        if getattr(self, worst) < LOW:
            return {"food": "hambriento", "hygiene": "sucio",
                    "fun": "aburrido", "energy": "cansado"}[worst]
        avg = sum(getattr(self, s) for s in STATS) / len(STATS)
        return "feliz" if avg >= 70 else "normal"

    def summary(self) -> str:
        vals = ", ".join(f"{LABELS[s].lower()} {int(getattr(self, s))}%" for s in STATS)
        return f"{self.name} está {self.mood}. {vals}."

    # ----------------------------------------------------------- persistencia
    def to_dict(self) -> dict:
        d = {s: getattr(self, s) for s in STATS}
        d.update(
            name=self.name, asleep=self.asleep, sleep_reason=self.sleep_reason,
            awake_override=self.awake_override, sleep_start=self.sleep_start,
            sleep_end=self.sleep_end, override_minutes=self.override_minutes,
            last_tick=self.last_tick.isoformat(),
            last_interaction=self.last_interaction.isoformat(),
        )
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Pet":
        now = datetime.now()
        p = cls(name=d.get("name", "Buddy"), sleep_start=int(d.get("sleep_start", 23)),
                sleep_end=int(d.get("sleep_end", 6)),
                override_minutes=int(d.get("override_minutes", 10)), now=now)
        for s in STATS:
            setattr(p, s, _clamp(float(d.get(s, getattr(p, s)))))
        p.asleep = bool(d.get("asleep", False))
        p.sleep_reason = d.get("sleep_reason")
        p.awake_override = bool(d.get("awake_override", False))
        p.last_tick = _parse_dt(d.get("last_tick"), now)
        p.last_interaction = _parse_dt(d.get("last_interaction"), now)
        return p
