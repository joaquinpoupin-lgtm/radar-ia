# Migración de Radar IA a otro computador

Revisado el 2026-10-21. Este archivo explica qué se lleva solo (con git), qué hay que copiar a mano y cómo dejar el proyecto funcionando en el computador nuevo.

> **Lo más importante:** el radar **no corre en este Mac**. Lo hace GitHub Actions cuatro veces al día y publica el sitio en GitHub Pages. Si apagas o cambias de computador, el radar sigue funcionando igual. El computador solo sirve para programar y probar.

---

## 1. Estado de git

| Qué | Estado |
|---|---|
| ¿Usa git? | Sí, rama `main` |
| Remoto | `origin` → https://github.com/joaquinpoupin-lgtm/radar-ia |
| Visibilidad | **Público** (necesario para que GitHub Pages sea gratis) |
| Cambios sin commitear | Ninguno (aparte de este archivo) |
| Archivos sin trackear | Ninguno (aparte de este archivo) |
| Commits sin subir | Ninguno: `main` está igual que `origin/main` |
| Stash | Vacío |
| Otras ramas locales | `respaldo-antes-correo` (solo existe en este Mac; ver abajo) |

### La rama `respaldo-antes-correo`: **no subirla nunca**

Es la copia de seguridad que se hizo en el Paso 11, antes de cambiar el autor de los commits por el correo privado de GitHub (`…@users.noreply.github.com`). Sus commits tienen **tu correo real y el nombre de este Mac**. Si se sube a GitHub, el correo queda publicado en un repo público.

- El código de esa rama es idéntico al de `main` en ese momento (se comparó en el Paso 11). No hace falta para nada.
- Opciones: dejarla solo en este Mac (recomendado), o borrarla cuando ya no te importe tenerla. Ojo: borrarla no se puede deshacer.
- Si igual quieres llevarla, se puede empaquetar en un archivo (`git bundle create respaldo.bundle respaldo-antes-correo`) y copiarlo a mano. **Nunca con `git push`.**

### Cómo dejar todo subido

Ya está todo subido. Lo único nuevo es este `MIGRACION.md`. Si quieres que quede en el repo, se puede commitear y subir (no tiene secretos ni datos personales).

---

## 2. Archivos que git no lleva

Según `.gitignore`, lo ignorado es:

| Archivo / carpeta | ¿Importa? | Qué hacer |
|---|---|---|
| `.env` | **Sí**: tiene tus claves `GEMINI_API_KEY` y `GROQ_API_KEY` para correr el radar en local | Copiar a mano (ver sección 5) o crear claves nuevas gratis |
| `.venv/` | No, se regenera | Se crea de nuevo con `python3 -m venv .venv` |
| `.pytest_cache/`, `__pycache__/` | No, se regenera | Nada |
| `_site/`, `_site.tmp/` | No, se regenera | Lo arma `python -m radar sitio` (el de internet lo arma Actions) |
| `.DS_Store` | No | Nada |

No hay `.env.local`, bases de datos locales, archivos de credenciales ni `.claude/settings.local.json` en el proyecto.

`data/` (noticias, caché y pendientes) **sí está en git**: el robot de GitHub la actualiza en cada corrida. Por eso, antes de correr el radar en local, siempre hay que hacer `git pull`.

### Secretos: revisado, no hay ninguno en el repo

- El test `tests/test_secretos.py` pasa: ninguna clave aparece en los archivos versionados, `.env` no está versionado y `.env.example` solo tiene los nombres.
- Se buscaron claves de Google (`AIza…`), Groq (`gsk_…`) y GitHub (`ghp_…`, `github_pat_…`) en **todo el historial de todas las ramas**: 0 coincidencias.
- Se buscaron los valores reales de `.env` en el historial y en los archivos: 0 coincidencias.
- En GitHub, las claves están como Secrets (`GEMINI_API_KEY`, `GROQ_API_KEY`), que no se pueden leer, solo reemplazar.

---

## 3. Configuración de Claude Code

### En el proyecto

| Archivo | Qué es | ¿Versionado? |
|---|---|---|
| `CLAUDE.md` | Instrucciones del proyecto: principios, comandos, decisiones y forma de trabajar | Sí |
| `.claude/launch.json` | Servidor `sitio` para ver la web en local (`python -m http.server 8000`) | Sí |
| `.claude/settings.json` / `settings.local.json` | No existen | — |
| `.claude/commands/`, `agents/`, `hooks/` | No existen | — |
| `.mcp.json` | No existe | — |

### A nivel de usuario (`~/.claude/` y `~/.claude.json`)

El proyecto **no depende** de nada definido a nivel de usuario:

- **Servidores MCP:** ninguno configurado, ni globales ni para este proyecto.
- **Comandos, agentes, hooks:** no hay (`~/.claude/commands`, `agents` y `hooks` no existen).
- `~/.claude/settings.json`: solo preferencias visuales (tema oscuro, pantalla completa). Copiarlo es opcional.
- `~/.claude/skills/logo-design` y los plugins instalados (por ejemplo, Playwright) no se usan en este proyecto.

### Historial de sesiones y memoria

Está en `~/.claude/projects/`, en la carpeta cuyo nombre termina en **`-IA-News`** (unos 12 MB, 5 sesiones). El nombre sale de la ruta completa del proyecto, con `/` y espacios cambiados por `-`. Adentro hay:

- Archivos `*.jsonl` (y carpetas con el mismo nombre): las conversaciones con Claude.
- `memory/`: la memoria de Claude sobre ti (`MEMORY.md` y `user-perfil.md`: español simple, no técnico, todo gratis). **Vale la pena copiarla.**

Si en el computador nuevo el proyecto queda en otra ruta (u otro usuario), la carpeta debe llamarse según la ruta nueva. Por ejemplo, `/Users/ana/IA News` → `-Users-ana-IA-News`. Lo más simple: abrir Claude Code una vez en el proyecto nuevo, cerrarlo y copiar el contenido dentro de la carpeta que se creó.

No es obligatorio copiar el historial: el estado del proyecto vive en `docs/plan-fase-1.md` (plan y bitácora) y `docs/diseno.md`, que van con git.

---

## 4. Requisitos para que corra

| Qué | Versión / detalle |
|---|---|
| Python | **3.12 o más nuevo** (`pyproject.toml`). En este Mac: 3.13.12. GitHub Actions usa 3.12 |
| Gestor de paquetes | `pip` + entorno virtual `venv` (vienen con Python) |
| Dependencias | `requirements.txt`: feedparser, httpx, Jinja2, PyYAML (versiones fijas). `requirements-dev.txt` suma pytest |
| git | Cualquier versión reciente (aquí: 2.50) |
| GitHub CLI `gh` | Opcional, para lanzar corridas y ver Secrets desde la terminal. Se instala con Homebrew (`brew install gh`); aquí: 2.102 |
| Homebrew | Solo si quieres instalar `gh` así |
| Node, Docker, bases de datos | **No se usan** |

**Servicios externos** (todos gratis, sin tarjeta, ya creados; las cuentas no dependen del computador):

- **GitHub:** repo, Actions (el robot), Pages (el sitio) y Secrets.
- **Google AI Studio:** clave de Gemini (IA principal).
- **Groq:** clave de respaldo.

**Variables de entorno** (solo los nombres):

- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- Fase 2 (todavía no): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

---

## 5. Archivos a copiar a mano

| Archivo | Desde dónde | Cómo copiarlo |
|---|---|---|
| `.env` | Raíz del proyecto | Por AirDrop o un pendrive. **Nunca** por correo, chat ni subido a la nube. Alternativa más segura: crear claves nuevas gratis en https://aistudio.google.com/apikey y https://console.groq.com/keys y escribirlas en un `.env` nuevo (copiando `.env.example`). Si creas claves nuevas, actualiza también los Secrets de GitHub y borra las viejas |
| Memoria de Claude (opcional) | `~/.claude/projects/<carpeta que termina en -IA-News>/memory/` | AirDrop o pendrive, a la carpeta equivalente del computador nuevo |
| Sesiones de Claude (opcional) | La misma carpeta, archivos `*.jsonl` y sus carpetas | Igual que la memoria |
| `~/.claude/settings.json` (opcional) | Tu carpeta personal | Solo tema y pantalla; también se pueden elegir de nuevo en el otro computador |

---

## 6. Pasos en el computador nuevo

1. Instalar Python 3.12+ y git (y `gh` si lo quieres: `brew install gh`, luego `gh auth login`).
2. Bajar el proyecto:
   ```bash
   git clone https://github.com/joaquinpoupin-lgtm/radar-ia.git "IA News"
   ```
3. **Configurar el correo privado de GitHub en este repo.** Esta configuración vive en `.git/config` y **no viaja con el clone**. Sin ella, tus commits saldrían con tu correo real en un repo público:
   ```bash
   git config user.name "Joaquín Poupin"
   git config user.email "267127855+joaquinpoupin-lgtm@users.noreply.github.com"
   ```
4. Crear el entorno e instalar dependencias:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```
5. Poner el `.env` en la raíz del proyecto (sección 5).
6. Comprobar que todo anda:
   ```bash
   python -m pytest -q          # deben pasar todos los tests (151 al 2026-10-21)
   python -m radar probar-ia    # Gemini y Groq responden OK
   python -m radar fuentes      # tabla de fuentes (los canales de YouTube fallan por ahora: está anotado)
   ```
7. (Opcional) Copiar la memoria y las sesiones de Claude (sección 3).
8. Antes de cada corrida local: `git pull` (el robot escribe `data/`).

### Checklist final

- [ ] `git status` limpio y `git log -1` igual que en GitHub
- [ ] `git config user.email` muestra el correo `…@users.noreply.github.com`
- [ ] `.env` presente y `python -m radar probar-ia` en OK
- [ ] Tests en verde
- [ ] La rama `respaldo-antes-correo` **no** está en GitHub (`git ls-remote origin` muestra solo `main`)
