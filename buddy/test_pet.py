"""Pruebas de la lógica de la mascota y del lector de .ics (solo librería estándar).

Ejecutar con:  uv run python -m unittest -v
"""
import unittest
from datetime import datetime, timedelta

from calendar_io import parse_ics
from pet import Pet


def at(h, m=0):
    return datetime(2026, 11, 19, h, m)


class PetTests(unittest.TestCase):
    def test_needs_decay_with_time(self):
        p = Pet(now=at(10))
        p.update(at(12))
        self.assertLess(p.food, 80)
        self.assertLess(p.hygiene, 80)
        self.assertLess(p.fun, 80)

    def test_actions_improve_needs(self):
        p = Pet(now=at(10))
        p.update(at(14))
        before = (p.food, p.hygiene, p.fun)
        p.feed(at(14)); p.bathe(at(14)); p.play(at(14))
        self.assertGreater(p.food, before[0])
        self.assertGreater(p.hygiene, before[1] - 6)
        self.assertGreater(p.fun, before[2])

    def test_sleeps_at_night_and_wakes_in_morning(self):
        p = Pet(now=at(22))
        p.update(at(22, 30))
        self.assertFalse(p.asleep)
        events = p.update(at(23, 30))
        self.assertTrue(p.asleep)
        self.assertIn("sleep:night", events)
        events = p.update(datetime(2026, 11, 20, 7, 0))
        self.assertFalse(p.asleep)
        self.assertIn("woke", events)

    def test_user_can_wake_it_at_night_then_it_sleeps_again(self):
        p = Pet(now=at(22))
        p.update(at(23, 30))
        self.assertTrue(p.asleep)
        self.assertTrue(p.wake_up(at(23, 31)))
        p.update(at(23, 40))
        self.assertFalse(p.asleep)             # sigue despierto ayudando
        p.update(at(23, 55))                   # >10 min sin interacción
        self.assertTrue(p.asleep)

    def test_exhausted_pet_falls_asleep_in_daytime(self):
        p = Pet(now=at(10))
        p.energy = 6
        p.update(at(10, 30))
        self.assertTrue(p.asleep)
        self.assertEqual(p.sleep_reason, "tired")

    def test_cannot_play_when_exhausted(self):
        p = Pet(now=at(10))
        p.energy = 10
        ok, _ = p.play(at(10))
        self.assertFalse(ok)

    def test_save_and_load(self):
        p = Pet(name="Pepe", now=at(10))
        p.update(at(11))
        q = Pet.from_dict(p.to_dict())
        self.assertEqual(q.name, "Pepe")
        self.assertAlmostEqual(q.food, p.food)


class IcsTests(unittest.TestCase):
    def test_parse_basic_event(self):
        ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:abc\nDTSTART:20261120T150000\n"
               "SUMMARY:Entrega final IA\nEND:VEVENT\nEND:VCALENDAR")
        ev = parse_ics(ics)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["title"], "Entrega final IA")
        self.assertEqual(ev[0]["start"], datetime(2026, 11, 20, 15, 0))


if __name__ == "__main__":
    unittest.main()
