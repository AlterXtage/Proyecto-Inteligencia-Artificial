# Buddy: asistente virtual con mascota

Asistente de escritorio (Python + Tkinter) con:

- **Mascota**: necesita comida, baño y juego; su ánimo y su cara cambian según sus necesidades.
- **Ciclo de sueño**: duerme de 11 pm a 6 am (configurable en `pet.py`) y se despierta en la mañana.
  Si le escribes mientras duerme, se despierta a ayudarte y vuelve a dormir tras 10 min sin actividad.
  También se duerme sola si se queda sin energía.
- **Recordatorios y calendario**: lenguaje natural en español + importación de `.ics` (Google Calendar, Outlook...).
  Un recordatorio vencido despierta a la mascota para avisarte.
- **Archivos y programas**: búsqueda aproximada por nombre y por contenido; abre archivos y programas
  instalados en tu PC («abre chrome», «ábreme la calculadora», «abre word»). En Windows incluye las
  apps de la Tienda (Calculadora, Configuración...) y reconoce nombres en español.
- **Agente de IA local**: cualquier cosa que no sea un comando (preguntas, charla, ayuda con tareas) se la
  pasa a un modelo de lenguaje que corre en tu propio computador con **Ollama**, sin internet.
  La respuesta se escribe en tiempo real, recuerda los últimos turnos de la charla y su personalidad
  cambia según su estado (hambre, sueño...).

## Instalación y uso (con uv)

```bash
uv sync              # instala las dependencias de Python
uv run main.py       # abre la aplicación
```

### Activar el chat con IA local (Ollama)

1. Instala Ollama desde https://ollama.com y déjalo abierto (corre en segundo plano).
2. Descarga un modelo una sola vez (necesita internet solo para esta descarga):

   ```bash
   ollama pull llama3.2
   ```

3. Abre Buddy con `uv run main.py` y escríbele cualquier cosa.

Para usar otro modelo (por ejemplo uno más grande, o `qwen2.5:3b`, `gemma3`, `mistral`):

```bash
# Windows (PowerShell):  $env:BUDDY_MODEL="qwen2.5:3b"
# macOS/Linux:           export BUDDY_MODEL="qwen2.5:3b"
```

Si Ollama no está abierto o no hay modelo instalado, Buddy sigue funcionando con todos sus
comandos y te avisa qué falta para poder charlar. Si el modelo configurado no está instalado
pero hay otro, usa ese.

Pruebas:

```bash
uv run python -m unittest -v
```

> Tkinter viene incluido en los Python que instala uv (Windows, macOS, Linux).
> Si usas un Python del sistema en Linux, instala `python3-tk`.

## Ejemplos de lo que puedes escribir

| Quiero... | Escribo... |
|---|---|
| Crear un recordatorio | `recuérdame mañana a las 3 pm estudiar IA` |
| Crear un evento | `agéndame reunión con el profe el viernes a las 10 am` |
| Ver mi agenda | `qué tengo hoy` / `mis eventos` |
| Borrar un recordatorio | `borra el recordatorio 3` |
| Buscar un archivo | `busca el informe de redes` (luego escribe el número para abrirlo) |
| Abrir un programa | `abre chrome`, `ábreme la calculadora`, `ejecuta spotify` |
| Cuidar a la mascota | `dame de comer`, `báñate`, `juguemos` |
| Dormir / despertar | `duérmete`, `despierta` |
| Cambiar su nombre | `te llamas Max` |

## Estructura

| Archivo | Qué hace |
|---|---|
| `main.py` | Punto de entrada |
| `pet.py` | Necesidades, ánimo y ciclo de sueño (máquina de estados) |
| `assistant.py` | Interpreta los mensajes y ejecuta acciones |
| `storage.py` | SQLite: estado de la mascota y recordatorios |
| `calendar_io.py` | Importador de `.ics` |
| `search.py` | Búsqueda de archivos y apertura de programas (rapidfuzz) |
| `llm.py` | Chat con un modelo local vía Ollama (respuesta en streaming + memoria de la charla) |
| `ui.py` | Interfaz Tkinter, animación y minijuego |
| `test_pet.py`, `test_llm.py`, `test_apps.py` | Pruebas unitarias (Ollama y la apertura de programas se simulan) |

Los datos se guardan en la carpeta de datos del usuario (`platformdirs`); puedes cambiarla con la variable `BUDDY_DB`.
