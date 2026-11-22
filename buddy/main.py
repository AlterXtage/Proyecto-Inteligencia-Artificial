"""Punto de entrada: uv run main.py"""
from assistant import Assistant
from pet import Pet
from search import AppIndex, FileIndex
from storage import Storage
from ui import BuddyApp


def main() -> None:
    storage = Storage()
    data = storage.load_pet()
    pet = Pet.from_dict(data) if data else Pet()

    files = FileIndex()
    files.build_async()          # indexa tus carpetas en segundo plano
    apps = AppIndex()
    apps.build_async()           # lista tus programas en segundo plano

    assistant = Assistant(pet, storage, files, apps)
    BuddyApp(pet, storage, assistant).mainloop()


if __name__ == "__main__":
    main()
