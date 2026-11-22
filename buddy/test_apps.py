"""Pruebas de la apertura de programas (no abren nada de verdad).

Si rapidfuzz / platformdirs no están instalados, usa versiones simuladas mínimas.
Ejecutar con:  uv run python -m unittest -v
"""
import difflib
import sys
import types
import unittest

try:
    import rapidfuzz  # noqa: F401
except ImportError:
    def _wratio(a, b):
        return 95.0 if (a in b or b in a) else difflib.SequenceMatcher(None, a, b).ratio() * 100

    def _extract(q, choices, scorer=None, limit=5, score_cutoff=0):
        scored = [(c, scorer(q, c), i) for i, c in enumerate(choices)]
        scored = [t for t in scored if t[1] >= score_cutoff]
        scored.sort(key=lambda t: -t[1])
        return scored[:limit]

    sys.modules["rapidfuzz"] = types.SimpleNamespace(
        fuzz=types.SimpleNamespace(WRatio=_wratio),
        process=types.SimpleNamespace(extract=_extract))

try:
    import platformdirs  # noqa: F401
except ImportError:
    sys.modules["platformdirs"] = types.SimpleNamespace(user_data_dir=lambda *a, **k: ".")

import search  # noqa: E402
from assistant import Assistant  # noqa: E402
from pet import Pet  # noqa: E402
from storage import Storage  # noqa: E402


class SearchTests(unittest.TestCase):
    def test_parse_start_apps_list_and_single(self):
        many = '[{"Name":"Calculadora","AppID":"Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},{"Name":"Chrome","AppID":"C:\\\\chrome.exe"}]'
        self.assertEqual(search._parse_start_apps(many)[0],
                         ("Calculadora", "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"))
        self.assertEqual(len(search._parse_start_apps(many)), 2)
        single = '{"Name":"Paint","AppID":"Microsoft.Paint_8wekyb3d8bbwe!App"}'
        self.assertEqual(len(search._parse_start_apps(single)), 1)
        self.assertEqual(search._parse_start_apps("no es json"), [])

    def test_aliases_only_added_when_missing(self):
        apps = {"Calculadora": "uwp"}
        search._merge_aliases(apps, {"calculadora": "calc", "bloc de notas": "notepad"})
        self.assertEqual(apps["Calculadora"], "uwp")          # no se pisa
        self.assertEqual(apps["Bloc de notas"], "notepad")    # se agrega
        self.assertEqual(len(apps), 2)

    def test_search_finds_app_by_partial_name(self):
        idx = search.AppIndex()
        idx.apps = [("Chrome Remote Desktop", "a"), ("Google Chrome", "b"), ("Bloc de notas", "c")]
        idx._norms = [search.normalize(n) for n, _ in idx.apps]
        idx._loaded = True
        hits = idx.search("chrome")
        self.assertIn("Google Chrome", [h.name for h in hits])
        self.assertGreaterEqual(hits[0].score, 75)


class FakeApps:
    CATALOG = ["Microsoft Word", "Google Chrome", "Calculadora", "Spotify"]

    def search(self, q, limit=3):
        return [search.Hit(n, "cmd:" + n, 92.0, "programa") for n in self.CATALOG
                if q and q in search.normalize(n)]


class FakeFiles:
    ready = True

    def search(self, q, limit=5):
        return []


class OpenAppRoutingTests(unittest.TestCase):
    def setUp(self):
        self.launched = []
        self._orig = search.AppIndex.launch
        search.AppIndex.launch = staticmethod(lambda hit: self.launched.append(hit.name))
        self.bot = Assistant(Pet(), Storage(":memory:"), FakeFiles(), FakeApps())

    def tearDown(self):
        search.AppIndex.launch = self._orig

    def test_open_chrome(self):
        r = self.bot.handle("abre chrome")
        self.assertEqual(self.launched, ["Google Chrome"])
        self.assertIn("Abriendo Google Chrome", r.text)

    def test_word_is_an_app_not_a_file(self):
        self.bot.handle("abre word")
        self.assertEqual(self.launched, ["Microsoft Word"])

    def test_polite_spanish_phrasing(self):
        self.bot.handle("ábreme la calculadora por favor")
        self.assertEqual(self.launched, ["Calculadora"])

    def test_other_verbs(self):
        self.bot.handle("ejecuta spotify")
        self.bot.handle("inicia google chrome")
        self.assertEqual(self.launched, ["Spotify", "Google Chrome"])

    def test_document_request_goes_to_files(self):
        r = self.bot.handle("abre el documento informe final")
        self.assertEqual(self.launched, [])
        self.assertIn("No encontré", r.text)


if __name__ == "__main__":
    unittest.main()
