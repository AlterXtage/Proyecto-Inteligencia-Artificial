"""Pruebas de llm.py con un Ollama simulado (no necesita Ollama instalado).

Ejecutar con:  uv run python -m unittest -v
"""
import sys
import types
import unittest


class FakeModel:
    def __init__(self, model):
        self.model = model


class FakeClient:
    installed = ["llama3.2:latest"]
    fail_list = False
    last_messages = None

    def __init__(self, *a, **kw):
        pass

    def list(self):
        if FakeClient.fail_list:
            raise ConnectionError("sin servidor")
        return types.SimpleNamespace(models=[FakeModel(n) for n in FakeClient.installed])

    def chat(self, model, messages, stream):
        FakeClient.last_messages = messages
        for piece in ["Ho", "la ", "mundo"]:
            yield {"message": {"content": piece}}


sys.modules["ollama"] = types.SimpleNamespace(Client=FakeClient)

import llm  # noqa: E402


class LlmTests(unittest.TestCase):
    def setUp(self):
        FakeClient.installed = ["llama3.2:latest"]
        FakeClient.fail_list = False
        llm.MODEL = "llama3.2"
        llm._cache.update(t=0.0, model=None, error=None)
        llm.reset()

    def test_streams_pieces_and_keeps_history(self):
        pieces = list(llm.stream("hola", "Buddy está feliz.", "Buddy"))
        self.assertEqual("".join(pieces), "Hola mundo")
        list(llm.stream("¿y ahora?", "Buddy está feliz.", "Buddy"))
        roles = [m["role"] for m in FakeClient.last_messages]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertIn("Buddy está feliz.", FakeClient.last_messages[0]["content"])

    def test_picks_configured_model_with_tag(self):
        model, error = llm.status(force=True)
        self.assertEqual(model, "llama3.2:latest")
        self.assertIsNone(error)

    def test_falls_back_to_other_installed_model(self):
        FakeClient.installed = ["nomic-embed-text:latest", "qwen2.5:3b"]
        self.assertEqual(llm.status(force=True)[0], "qwen2.5:3b")

    def test_no_models_gives_instructions(self):
        FakeClient.installed = []
        model, error = llm.status(force=True)
        self.assertIsNone(model)
        self.assertIn("ollama pull", error)

    def test_ollama_not_running(self):
        FakeClient.fail_list = True
        self.assertFalse(llm.available())
        self.assertIn("ollama.com", llm.status()[1])
        self.assertIn("ollama.com", "".join(llm.stream("hola", "", "Buddy")))


if __name__ == "__main__":
    unittest.main()
