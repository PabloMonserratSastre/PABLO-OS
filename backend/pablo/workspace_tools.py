"""Local specialist tools with a scoped file boundary and explicit execution risk.

The path boundary is a file-operation policy, NOT an operating-system sandbox.
code.run executes user-approved code with the worker account's OS permissions.
"""

import csv
from contextvars import ContextVar
import hashlib
import html
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

from sqlalchemy import func, select

from .db import Item, Schedule
from .scheduling import parse_instant

MAX_FILE_BYTES = 200_000
MAX_OUTPUT_BYTES = 32_000
MAX_SCAN_FILES = 500
PROJECT_ROOT = Path(__file__).resolve().parents[2]
workspace_override = ContextVar("workspace_override", default=None)
PRIVATE_NAMES = {
    ".git", ".ssh", ".aws", ".azure", ".gnupg", ".codex", ".agents",
    "credentials", "credentials.json", "secrets", "secrets.json", "secrets.yaml",
    "secrets.yml", "id_rsa", "id_ed25519", "id_ecdsa", ".npmrc", ".pypirc",
    ".netrc", ".docker",
}
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".db", ".sqlite", ".sqlite3"}
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"),
    re.compile(r"(?im)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[=:]\s*['\"]([^'\"\r\n]{8,})['\"]"),
]


def _arguments(args, required=(), optional=()):
    if not isinstance(args, dict) or set(args) - set(required) - set(optional):
        raise ValueError("Argumentos desconocidos para esta herramienta.")
    if any(name not in args for name in required):
        raise ValueError("Faltan argumentos: " + ", ".join(name for name in required if name not in args))


def _text(args, key, *, default=None, maximum=MAX_FILE_BYTES, allow_empty=False):
    value = args.get(key, default)
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()):
        raise ValueError(f"{key}: escribe texto válido (máximo {maximum} caracteres).")
    return value


def _integer(args, key, default, low, high):
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{key}: debe ser un entero entre {low} y {high}.")
    return value


def _boolean(args, key, default=False):
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key}: debe ser true o false.")
    return value


def _private(name):
    name = name.lower()
    return name in PRIVATE_NAMES or name.startswith(".env") or Path(name).suffix in PRIVATE_SUFFIXES


def _check_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("No se admiten enlaces simbólicos, junctions ni puntos de reanálisis.")
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise ValueError("No se admiten archivos con enlaces duros.")


def workspace_root():
    root = Path(workspace_override.get() or os.getenv("PABLO_WORKSPACE_ROOT", str(PROJECT_ROOT / "generated"))).expanduser().absolute()
    # Check before resolve: resolving first would hide a configured junction.
    for part in [*reversed(root.parents), root]:
        _check_link(part)
    return root.resolve()


def workspace_path(value=".", *, existing=False):
    if not isinstance(value, str) or not value or len(value) > 500:
        raise ValueError("Escribe una ruta relativa al workspace.")
    if any(ord(c) < 32 for c in value) or ":" in value or PureWindowsPath(value).is_absolute():
        raise ValueError("No se admiten rutas absolutas, unidades ni flujos alternativos.")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/"):
        raise ValueError("La ruta debe ser relativa al workspace.")
    parts = normalized.split("/")
    for part in parts:
        if part in {"", "."}:
            continue
        if part == ".." or part.endswith((".", " ")) or _private(part):
            raise ValueError("Ruta protegida o fuera del workspace.")
        if re.match(r"(?i)^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part):
            raise ValueError("Nombre reservado por el sistema operativo.")
        if any(c in part for c in '<>"|?*'):
            raise ValueError("La ruta contiene caracteres no permitidos.")
    root = workspace_root()
    path = root.joinpath(*[part for part in parts if part and part != "."])
    for parent in [root, *[root.joinpath(*path.relative_to(root).parts[:i]) for i in range(1, len(path.relative_to(root).parts) + 1)]]:
        _check_link(parent)
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("La ruta sale del workspace configurado.")
    if existing and not resolved.exists():
        raise ValueError("No existe esa ruta en el workspace.")
    return resolved


def _relative(path):
    return path.relative_to(workspace_root()).as_posix()


def _secret(text):
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _redact(text):
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[CREDENCIAL OCULTA]", text)
    return text


def _read(path, *, secret_check=True):
    path = workspace_path(_relative(path), existing=True)
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Se requiere un archivo de texto de hasta 200 KB.")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES or b"\x00" in data:
        raise ValueError("Archivo binario o demasiado grande.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("El archivo debe usar UTF-8.") from exc
    if secret_check and _secret(text):
        raise ValueError("El archivo parece contener credenciales. Usa security.audit para revisar su ubicación sin revelarlas.")
    return text


def _write(relative, content, overwrite=False):
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("Máximo 200 KB por archivo.")
    if _secret(content):
        raise ValueError("No guardes credenciales en archivos de trabajo; utiliza la configuración privada.")
    path = workspace_path(relative)
    if path.exists() and (not overwrite or not path.is_file()):
        raise ValueError("El destino ya existe. Revisa su contenido antes de autorizar overwrite=true.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path = workspace_path(relative)
    fd, temporary = tempfile.mkstemp(prefix=".pablo-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        workspace_path(relative)
        if overwrite:
            os.replace(temporary, path)
        else:
            # 'xb' is exclusive on Windows and POSIX, so concurrent writes cannot overwrite.
            with path.open("xb") as destination:
                destination.write(encoded)
    except FileExistsError as exc:
        raise ValueError("El destino ya existe; no se sobrescribió.") from exc
    finally:
        Path(temporary).unlink(missing_ok=True)
    actual = path.read_bytes()
    return {"path": _relative(path), "bytes": len(actual), "sha256": hashlib.sha256(actual).hexdigest(), "verified": actual == encoded}


def _walk(path, limit=MAX_SCAN_FILES):
    visited = 0
    for directory, folders, names in os.walk(path, followlinks=False):
        accepted = []
        for folder in sorted(folders):
            if folder in SKIP_DIRS or _private(folder):
                continue
            try:
                workspace_path(_relative(Path(directory) / folder), existing=True)
                accepted.append(folder)
            except ValueError:
                continue
        folders[:] = accepted
        for name in sorted(names):
            if _private(name) or name.startswith(".pablo-"):
                continue
            try:
                candidate = workspace_path(_relative(Path(directory) / name), existing=True)
            except ValueError:
                continue
            if not candidate.is_file():
                continue
            visited += 1
            if visited > limit:
                return
            yield candidate


def workspace_list(db, args, project_id):
    _arguments(args, optional=("path", "limit"))
    path = workspace_path(args.get("path", "."))
    limit = _integer(args, "limit", 100, 1, 500)
    if not path.exists():
        return {"path": _relative(path), "files": [], "truncated": False}
    if not path.is_dir():
        raise ValueError("La ruta debe ser una carpeta.")
    paths = list(_walk(path, limit + 1))
    return {"path": _relative(path), "files": [{"path": _relative(p), "bytes": p.stat().st_size} for p in paths[:limit]], "truncated": len(paths) > limit}


def workspace_read(db, args, project_id):
    _arguments(args, required=("path",))
    path = workspace_path(args["path"], existing=True)
    content = _read(path)
    return {"path": _relative(path), "content": content, "bytes": len(content.encode("utf-8"))}


def workspace_write(db, args, project_id):
    _arguments(args, required=("path", "content"), optional=("overwrite",))
    return _write(args["path"], _text(args, "content", allow_empty=True), _boolean(args, "overwrite"))


def _environment():
    # Never inherit provider tokens, PYTHONPATH, NODE_OPTIONS, Git config or proxies.
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "LANG") if key in os.environ}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    return env


def _terminate(process):
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def _execute(command, directory, timeout=20):
    if not Path(command[0]).is_absolute():
        raise ValueError("El ejecutable debe estar resuelto por el servidor.")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    try:
        process = subprocess.Popen(command, cwd=directory, env=_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, **options)
    except OSError as exc:
        raise ValueError("No se ha podido iniciar el intérprete instalado.") from exc
    captured = bytearray()
    limit_reached = threading.Event()

    def collect():
        try:
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                remaining = MAX_OUTPUT_BYTES - len(captured)
                captured.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    limit_reached.set()
                    break
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    started = time.monotonic()
    timed_out = False
    while process.poll() is None:
        if limit_reached.is_set() or time.monotonic() - started >= timeout:
            timed_out = not limit_reached.is_set()
            _terminate(process)
            break
        time.sleep(0.025)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate(process)
    reader.join(timeout=1)
    # A descendant that inherited stdout must not keep the request open forever.
    if reader.is_alive():
        _terminate(process)
        reader.join(timeout=1)
    if not reader.is_alive():
        process.stdout.close()
    return {"exit_code": process.returncode, "output": _redact(bytes(captured).decode("utf-8", errors="replace")), "timed_out": timed_out, "truncated": limit_reached.is_set(), "duration_ms": round((time.monotonic() - started) * 1000), "verified": process.returncode == 0 and not timed_out and not limit_reached.is_set()}


def code_run(db, args, project_id):
    _arguments(args, required=("path", "runner"), optional=("timeout_seconds",))
    runner = args["runner"]
    timeout = _integer(args, "timeout_seconds", 20, 1, 60)
    path = workspace_path(args["path"], existing=True)
    directory = path if path.is_dir() else path.parent
    if runner in {"python", "node"}:
        if not path.is_file() or path.suffix.lower() not in ({".py"} if runner == "python" else {".js", ".mjs", ".cjs"}):
            raise ValueError("El runner requiere un archivo de código de su lenguaje.")
        _read(path)
        if runner == "python":
            command = [str(Path(sys.executable).resolve()), "-I", "-B", str(path)]
        else:
            executable = shutil.which("node")
            if not executable:
                raise ValueError("Node.js no está instalado o no está en PATH.")
            command = [str(Path(executable).resolve()), str(path)]
    elif runner in {"unittest", "pytest"}:
        if not path.is_dir():
            raise ValueError("Los tests requieren una carpeta del workspace.")
        command = [str(Path(sys.executable).resolve()), "-I", "-B", "-m"]
        if runner == "unittest":
            command += ["unittest", "discover", "-s", str(path), "-p", "test*.py"]
        else:
            command += ["pytest", "-q", "-o", "addopts=", "-o", "cache_dir=" + str(path / ".pytest_cache"), str(path)]
    else:
        raise ValueError("Runner permitido: python, node, unittest o pytest.")
    result = _execute(command, directory, timeout)
    return {"path": _relative(path), "runner": runner, **result, "scope": "Código ejecutado con los permisos del usuario del worker. No es un sandbox; sin shell libre y con límites de tiempo y salida."}


def _git(path):
    executable = shutil.which("git")
    if not executable:
        raise ValueError("Git no está instalado o no está en PATH.")
    directory = workspace_path(path, existing=True)
    if not directory.is_dir():
        raise ValueError("Indica la carpeta del repositorio.")
    repository = directory
    root = workspace_root()
    while not (repository / ".git").exists():
        if repository == root:
            raise ValueError("No hay un repositorio Git dentro del workspace en esa ruta.")
        repository = repository.parent
    # Linked worktrees and gitdir indirections are not within this adapter's scope.
    gitdir = repository / ".git"
    _check_link(gitdir)
    if not gitdir.is_dir():
        raise ValueError("No se admiten worktrees con gitdir externo.")
    metadata_count = 0
    for current, folders, names in os.walk(gitdir, followlinks=False):
        for name in [*folders, *names]:
            _check_link(Path(current) / name)
            metadata_count += 1
            if metadata_count > 20_000:
                raise ValueError("Repositorio demasiado grande para este adaptador local (20.000 entradas Git).")
    config_path = gitdir / "config"
    if config_path.exists():
        if config_path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Configuración Git demasiado grande.")
        if re.search(r"(?im)^\s*\[include(?:if)?(?:\s|\])", config_path.read_text(encoding="utf-8", errors="replace")):
            raise ValueError("No se admiten inclusiones externas en la configuración Git del workspace.")
    if (gitdir / "objects" / "info" / "alternates").exists():
        raise ValueError("No se admiten almacenes Git externos mediante alternates.")
    command = [str(Path(executable).resolve()), "--no-pager", "--git-dir=" + str(gitdir), "--work-tree=" + str(repository), "-c", "core.bare=false", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull, "-c", "core.untrackedCache=false", "-c", "diff.external=", "-c", "core.pager=cat", "-C", str(repository)]
    return command, repository


def git_status(db, args, project_id):
    _arguments(args, optional=("path",))
    command, directory = _git(args.get("path", "."))
    result = _execute([*command, "status", "--short", "--branch", "--untracked-files=normal"], directory)
    return {"path": _relative(directory), **result}


def git_diff(db, args, project_id):
    _arguments(args, optional=("path", "staged"))
    command, directory = _git(args.get("path", "."))
    staged = ["--cached"] if _boolean(args, "staged") else []
    names = _execute([*command, "diff", *staged, "--name-only", "-z", "--no-ext-diff", "--no-textconv"], directory)
    if not names["verified"]:
        return {"path": _relative(directory), **names}
    selected = []
    skipped = 0
    for name in names["output"].split("\x00"):
        if not name:
            continue
        try:
            workspace_path((directory.relative_to(workspace_root()) / name).as_posix())
            selected.append(name)
        except ValueError:
            skipped += 1
    if not selected:
        return {"path": _relative(directory), "output": "No hay cambios visibles en archivos permitidos.", "skipped_private_files": skipped, "verified": True}
    result = _execute([*command, "diff", *staged, "--no-ext-diff", "--no-textconv", "--", *selected[:100]], directory)
    return {"path": _relative(directory), "skipped_private_files": skipped, "files_truncated": len(selected) > 100, **result}


def git_branch(db, args, project_id):
    _arguments(args, required=("name",), optional=("path",))
    name = _text(args, "name", maximum=100)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,99}", name) or "//" in name or name.endswith("/"):
        raise ValueError("Usa un nombre de rama con letras, números, guiones y barras.")
    command, directory = _git(args.get("path", "."))
    result = _execute([*command, "branch", "--", name], directory)
    return {"path": _relative(directory), "branch": name, "checked_out": False, **result}


def _slug(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")[:60] or "proyecto"


APP_HTML = '''<!doctype html>
<html lang="es"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{font:16px system-ui;color:#eef3ff;background:#101526;color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;padding:40px 20px}main{max-width:820px;margin:auto}header{display:flex;justify-content:space-between;align-items:center}h1{font-size:clamp(2rem,6vw,3.8rem);margin:12px 0}p{color:#aebbd8;line-height:1.6}.card{padding:24px;background:#1a2238;border:1px solid #35405d;border-radius:18px;margin:24px 0}form{display:flex;gap:10px;flex-wrap:wrap}input,select,button{font:inherit;padding:12px;border:1px solid #516084;border-radius:9px}input{flex:1;min-width:180px;background:#101526}button{background:#b7edb4;color:#142518;cursor:pointer}button.secondary{background:#273451;color:#eef3ff}ul{padding:0;list-style:none}li{display:flex;align-items:center;gap:12px;padding:15px 0;border-bottom:1px solid #35405d}li span{flex:1;overflow-wrap:anywhere}li.done span{text-decoration:line-through;color:#aebbd8}li input{flex:0;min-width:0;width:20px;height:20px}.meta{font-size:.85rem}#notice{min-height:24px;color:#fbd18a}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #96aaff;outline-offset:3px}</style>
<main><header><b>MI ESPACIO</b><span id="count" aria-live="polite"></span></header><h1>__TITLE__</h1><p>__DESCRIPTION__</p>
<section class="card"><form id="new-task"><label for="task" class="meta">Nueva tarea</label><input id="task" maxlength="250" required placeholder="¿Qué quieres conseguir?"><button>Añadir tarea</button></form><p id="notice" role="status"></p><label for="filter">Mostrar </label><select id="filter"><option value="all">Todas</option><option value="pending">Pendientes</option><option value="done">Completadas</option></select><ul id="tasks"></ul><p id="empty">Añade tu primera tarea para empezar.</p></section>
<button id="export" class="secondary">Exportar JSON</button><p class="meta">Tus tareas se guardan en este navegador. Exporta una copia para conservarlas.</p></main><script>
const storageKey='pablo-prototype-__SLUG__'; let tasks=[]; const notice=document.querySelector('#notice');
try{const parsed=JSON.parse(localStorage.getItem(storageKey)||'[]');tasks=Array.isArray(parsed)?parsed.filter(t=>t&&typeof t.title==='string'&&typeof t.id==='string').slice(0,2000):[]}catch{notice.textContent='El navegador no ha podido recuperar los datos guardados.'}
function save(){try{localStorage.setItem(storageKey,JSON.stringify(tasks))}catch{notice.textContent='No se puede guardar en este navegador. Exporta tus tareas.'}render()}
function render(){const list=document.querySelector('#tasks');list.replaceChildren();const filter=document.querySelector('#filter').value;const visible=tasks.filter(t=>filter==='all'||(filter==='done'?t.done:!t.done));for(const task of visible){const li=document.createElement('li');li.className=task.done?'done':'';const check=document.createElement('input');check.type='checkbox';check.checked=!!task.done;check.setAttribute('aria-label','Completar '+task.title);check.onchange=()=>{task.done=check.checked;save()};const title=document.createElement('span');title.textContent=task.title;const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='Eliminar';remove.setAttribute('aria-label','Eliminar '+task.title);remove.onclick=()=>{tasks=tasks.filter(t=>t.id!==task.id);save()};li.append(check,title,remove);list.append(li)}document.querySelector('#empty').hidden=!!visible.length;document.querySelector('#count').textContent=tasks.filter(t=>!t.done).length+' pendientes'}
document.querySelector('#new-task').onsubmit=e=>{e.preventDefault();const input=document.querySelector('#task'),title=input.value.trim();if(!title)return;if(tasks.length>=2000){notice.textContent='Límite de 2.000 tareas. Exporta y elimina tareas antiguas.';return}tasks.unshift({id:globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+Math.random().toString(36),title,done:false});input.value='';save();input.focus()};document.querySelector('#filter').onchange=render;
document.querySelector('#export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(tasks,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='tareas.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};render();
</script></html>'''


GAME_HTML = '''<!doctype html>
<html lang="es"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>*{box-sizing:border-box}body{margin:0;padding:24px;background:#101526;color:#eef4ff;font:16px system-ui}main{max-width:850px;margin:auto}h1{font-size:clamp(2rem,5vw,3rem);margin-bottom:8px}p{color:#aebbd8;line-height:1.6}canvas{display:block;width:100%;aspect-ratio:16/10;background:#141d35;border:1px solid #465272;border-radius:18px;touch-action:none}header,.controls{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin:18px 0}button{font:inherit;padding:12px 18px;border:0;border-radius:9px;background:#b7edb4;color:#10221a;cursor:pointer}button:focus-visible,canvas:focus-visible{outline:3px solid #a6b8ff;outline-offset:4px}#status{min-height:24px;color:#d2f5ca}</style>
<main><h1>__TITLE__</h1><p>__DESCRIPTION__</p><header><b>ESTRELLAS <span id="score">0</span></b><span>Récord <b id="best">0</b></span><span>Vidas <b id="lives">3</b></span></header><canvas id="game" width="800" height="500" tabindex="0" aria-label="Juego: mueve la nave con flechas o arrastrando. Recoge estrellas y evita meteoritos."></canvas><div class="controls"><button id="start">Comenzar</button><button id="pause">Pausar</button><span>Flechas / A y D · Arrastra en pantalla · P pausa</span></div><p id="status" role="status" aria-live="polite">Recoge estrellas doradas. Evita los meteoritos rojos.</p></main><script>
const canvas=document.querySelector('#game'),ctx=canvas.getContext('2d'),keys=new Set(),statusEl=document.querySelector('#status');let state='ready',score=0,lives=3,best=0,time=0,spawn=0,last=0,objects=[],player={x:400,y:440,r:18},invincible=0;
try{best=Number(localStorage.getItem('pablo-game-__SLUG__'))||0}catch{}document.querySelector('#best').textContent=best;
const stars=Array.from({length:55},()=>({x:Math.random()*800,y:Math.random()*500,r:Math.random()*1.5+.4}));
function hud(){document.querySelector('#score').textContent=score;document.querySelector('#lives').textContent=lives;document.querySelector('#best').textContent=best}
function start(){state='running';score=0;lives=3;time=0;spawn=0;objects=[];invincible=0;player.x=400;keys.clear();statusEl.textContent='¡A jugar!';document.querySelector('#start').textContent='Reiniciar';document.querySelector('#pause').textContent='Pausar';hud();canvas.focus()}
function pause(){if(state==='running'){state='paused';statusEl.textContent='En pausa';document.querySelector('#pause').textContent='Continuar'}else if(state==='paused'){state='running';statusEl.textContent='¡A jugar!';document.querySelector('#pause').textContent='Pausar'}}
function finish(){state='over';best=Math.max(best,score);try{localStorage.setItem('pablo-game-__SLUG__',String(best))}catch{}hud();statusEl.textContent='Partida terminada: '+score+' puntos. Pulsa Reiniciar para volver a jugar.'}
document.querySelector('#start').onclick=start;document.querySelector('#pause').onclick=pause;
document.addEventListener('keydown',e=>{if(e.target instanceof HTMLButtonElement||e.target instanceof HTMLInputElement)return;const key=e.key.toLowerCase();if(['arrowleft','arrowright','a','d','p',' '].includes(key)){e.preventDefault();keys.add(key);if(key==='p'&&!e.repeat)pause();if(key===' '&&state!=='running'&&state!=='paused')start()}});document.addEventListener('keyup',e=>keys.delete(e.key.toLowerCase()));window.addEventListener('blur',()=>{keys.clear();if(state==='running')pause()});document.addEventListener('visibilitychange',()=>{if(document.hidden&&state==='running')pause()});
function pointer(e){const rect=canvas.getBoundingClientRect();player.x=Math.max(player.r,Math.min(800-player.r,(e.clientX-rect.left)*800/rect.width))}canvas.addEventListener('pointerdown',e=>{canvas.setPointerCapture(e.pointerId);pointer(e)});canvas.addEventListener('pointermove',e=>{if(e.buttons||e.pointerType==='touch')pointer(e)});
function update(dt){time+=dt;invincible=Math.max(0,invincible-dt);player.x+=((keys.has('arrowright')||keys.has('d')?1:0)-(keys.has('arrowleft')||keys.has('a')?1:0))*420*dt;player.x=Math.max(player.r,Math.min(800-player.r,player.x));spawn-=dt;if(spawn<=0){spawn=Math.max(.18,.65-time*.005);objects.push({x:20+Math.random()*760,y:-25,r:12+Math.random()*9,speed:120+Math.random()*100+Math.min(time*3,230),star:Math.random()<.45})}for(const o of objects){o.y+=o.speed*dt;if(Math.hypot(player.x-o.x,player.y-o.y)<player.r+o.r){if(o.star){score+=10;o.y=600;hud()}else if(!invincible){lives--;o.y=600;invincible=1.1;hud();if(lives<=0){finish();break}}}}objects=objects.filter(o=>o.y<540)}
function draw(){ctx.clearRect(0,0,800,500);ctx.fillStyle='#e0eaff';for(const s of stars){ctx.globalAlpha=.4;ctx.beginPath();ctx.arc(s.x,(s.y+time*15)%500,s.r,0,Math.PI*2);ctx.fill()}ctx.globalAlpha=1;for(const o of objects){ctx.fillStyle=o.star?'#ffd977':'#ff7789';ctx.beginPath();if(o.star){for(let i=0;i<10;i++){const angle=-Math.PI/2+i*Math.PI/5,r=i%2?o.r*.45:o.r;const x=o.x+Math.cos(angle)*r,y=o.y+Math.sin(angle)*r;i?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.closePath()}else{ctx.arc(o.x,o.y,o.r,0,Math.PI*2)}ctx.fill()}ctx.save();ctx.translate(player.x,player.y);ctx.globalAlpha=invincible&&Math.floor(invincible*10)%2?.35:1;ctx.fillStyle='#acbaff';ctx.beginPath();ctx.moveTo(0,-23);ctx.lineTo(20,17);ctx.lineTo(0,10);ctx.lineTo(-20,17);ctx.closePath();ctx.fill();ctx.restore();if(state!=='running'){ctx.fillStyle='#0a1024bb';ctx.fillRect(0,0,800,500);ctx.fillStyle='#eef4ff';ctx.textAlign='center';ctx.font='bold 34px system-ui';ctx.fillText(state==='ready'?'ATRAPA LAS ESTRELLAS':state==='paused'?'PAUSA':'FIN DE PARTIDA',400,235);ctx.font='18px system-ui';ctx.fillText(state==='ready'?'Pulsa Comenzar':state==='paused'?'Pulsa Continuar o P':score+' puntos · Pulsa Reiniciar',400,275)}}
function frame(stamp){const dt=Math.min((stamp-last)/1000||0,.04);last=stamp;if(state==='running')update(dt);draw();requestAnimationFrame(frame)}requestAnimationFrame(frame);
</script></html>'''


def code_scaffold(db, args, project_id):
    _arguments(args, required=("name", "kind"), optional=("description", "html", "css", "javascript"))
    name = _text(args, "name", maximum=100)
    kind = args["kind"]
    if kind not in {"app", "game", "web"}:
        raise ValueError("Tipo de prototipo: app, game o web.")
    description = _text(args, "description", default="Un proyecto local creado con PABLO OS.", maximum=1000)
    slug = _slug(name)
    folder = workspace_path(slug)
    if folder.exists():
        raise ValueError("Ya existe una carpeta con ese nombre. Elige otro para conservar los archivos.")
    source = _text(args, "html") if kind == "web" else APP_HTML if kind == "app" else GAME_HTML
    source = source.replace("__TITLE__", html.escape(name)).replace("__DESCRIPTION__", html.escape(description)).replace("__SLUG__", slug)
    styles = re.findall(r"<style[^>]*>(.*?)</style>", source, re.S | re.I)
    scripts = re.findall(r"<script>(.*?)</script>", source, re.S | re.I)
    source = re.sub(r"<style[^>]*>.*?</style>", "", source, flags=re.S | re.I)
    source = re.sub(r"<script>.*?</script>", "", source, flags=re.S | re.I)
    style_link = '<link rel="stylesheet" href="styles.css">'
    script_link = '<script src="script.js" defer></script>'
    if re.search(r"</head>", source, re.I):
        source = re.sub(r"</head>", style_link + "\n</head>", source, count=1, flags=re.I)
    elif re.search(r"<html[^>]*>", source, re.I):
        source = re.sub(r"(<html[^>]*>)", lambda match: match[0] + "\n" + style_link, source, count=1, flags=re.I)
    else:
        source = '<!doctype html><html><head><meta charset="utf-8">' + style_link + "</head><body>" + source + "</body></html>"
    source = re.sub(r"</body>", script_link + "\n</body>", source, count=1, flags=re.I) if re.search(r"</body>", source, re.I) else re.sub(r"</html>", script_link + "\n</html>", source, count=1, flags=re.I) if re.search(r"</html>", source, re.I) else source + "\n" + script_link
    files = {"index.html": source, "project.json": json.dumps({"name": name, "kind": kind, "description": description, "entrypoint": "index.html", "created_by": "PABLO OS"}, ensure_ascii=False, indent=2) + "\n", "README.md": f"# {name}\n\n{description}\n\n## Arranque\n\nAbre index.html en tu navegador. No requiere dependencias ni servidor.\n\n## Alcance\n\n" + ("Gestor de tareas con filtros, persistencia en este navegador y exportación JSON." if kind == "app" else "Juego arcade con teclado/táctil, puntuación, vidas, récord local y pausa.") + "\n\nEste prototipo es una base editable; el contenido específico se adapta modificando index.html.\n", ".gitignore": "__pycache__/\n.pytest_cache/\nnode_modules/\n.env*\n"}
    files["styles.css"] = "\n".join(styles + [_text(args, "css", default="", allow_empty=True)])
    files["script.js"] = "\n".join(scripts + [_text(args, "javascript", default="", allow_empty=True)])
    if kind == "web":
        files["README.md"] = f"# {name}\n\n{description}\n\nAbre index.html junto a styles.css y script.js.\nRevisa las funciones solicitadas antes de publicar.\n"
    # Validate every file before reserving the folder or writing anything.
    for content in files.values():
        if len(content.encode("utf-8")) > MAX_FILE_BYTES or _secret(content):
            raise ValueError("El proyecto contiene un archivo demasiado grande o posibles credenciales.")
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        folder.mkdir()
    except FileExistsError:
        raise ValueError("Ya existe esa carpeta. Usa otro nombre para conservar sus archivos.") from None
    result = [_write(f"{slug}/{filename}", content) for filename, content in files.items()]
    return {"name": name, "kind": kind, "path": slug, "entrypoint": f"{slug}/index.html", "files": result, "run": "Abre index.html en tu navegador.", "scope": "Prototipo funcional de navegador, editable y sin dependencias externas.", "verified": all(item["verified"] for item in result)}


def security_audit(db, args, project_id):
    _arguments(args, optional=("path",))
    path = workspace_path(args.get("path", "."), existing=True)
    paths = list(_walk(path, MAX_SCAN_FILES + 1)) if path.is_dir() else [path]
    findings = []
    scanned = 0
    rules = [("critical", "Credencial potencial", _secret, "Retira la credencial del código y rótala si fue compartida."), ("high", "Ejecución de shell", lambda text: bool(re.search(r"\bshell\s*=\s*True|\bos\.system\s*\(|\bchild_process\b", text)), "Usa argumentos cerrados y evita concatenar entrada del usuario."), ("medium", "Evaluación dinámica", lambda text: bool(re.search(r"\b(?:eval|exec)\s*\(", text)), "Revisa si puede sustituirse por un parser o una lista de operaciones permitidas."), ("medium", "Verificación TLS desactivada", lambda text: bool(re.search(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false", text)), "Activa la validación de certificados TLS."), ("medium", "Inserción HTML dinámica", lambda text: bool(re.search(r"\.innerHTML\s*=|dangerouslySetInnerHTML", text)), "Evita insertar HTML no confiable; usa textContent o sanitización revisada.")]
    for candidate in paths[:MAX_SCAN_FILES]:
        try:
            content = _read(candidate, secret_check=False)
        except ValueError:
            continue
        scanned += 1
        for line_number, line in enumerate(content.splitlines(), 1):
            for severity, title, predicate, recommendation in rules:
                if predicate(line):
                    findings.append({"path": _relative(candidate), "line": line_number, "severity": severity, "title": title, "recommendation": recommendation})
                    if len(findings) >= 100:
                        break
            if len(findings) >= 100:
                break
        if len(findings) >= 100:
            break
    return {"path": _relative(path), "scanned_files": scanned, "findings": findings, "truncated": len(paths) > MAX_SCAN_FILES or len(findings) >= 100, "scope": "Revisión estática heurística local. No ejecuta código, no consulta vulnerabilidades publicadas y no garantiza ausencia de fallos. Los valores de credenciales nunca se muestran."}


def devops_diagnose(db, args, project_id):
    _arguments(args, optional=("path",))
    path = workspace_path(args.get("path", "."))
    checks = []
    for name in ("Dockerfile", "compose.yaml", "docker-compose.yml", "package.json", "requirements.txt", "pyproject.toml", "README.md", ".gitignore"):
        candidate = workspace_path((_relative(path).rstrip(".") + "/" + name).lstrip("/"))
        checks.append({"name": name, "present": candidate.is_file()})
    commands = {name: bool(shutil.which(name)) for name in ("git", "node", "docker")}
    disk = shutil.disk_usage(path if path.exists() else workspace_root().parent)
    recommendations = []
    found = {check["name"] for check in checks if check["present"]}
    if not found & {"requirements.txt", "pyproject.toml", "package.json"}:
        recommendations.append("No se detectó un manifiesto de dependencias en esta carpeta; un prototipo HTML puede funcionar sin él.")
    if "README.md" not in found:
        recommendations.append("Añade instrucciones reproducibles de instalación, pruebas y arranque.")
    if disk.free < 1_000_000_000:
        recommendations.append("Queda menos de 1 GB libre en el volumen del workspace.")
    return {"path": _relative(path), "python_version": sys.version.split()[0], "executables_available": commands, "configuration": checks, "disk_free_mb": disk.free // 1_000_000, "recommendations": recommendations, "scope": "Diagnóstico local de archivos, ejecutables y disco; no inicia servicios ni despliega infraestructura."}


def _project(db, project_id):
    if project_id:
        row = db.get(Item, project_id)
        if not row or row.kind != "projects":
            raise ValueError("Proyecto no encontrado.")


def _artifact(db, title, data, project_id):
    _project(db, project_id)
    item = Item(kind="artifacts", title=title, data={**data, "project_id": project_id})
    db.add(item)
    db.flush()
    return {"id": item.id, "title": title, **item.data, "verified": True}


def study_create(db, args, project_id):
    _arguments(args, required=("title", "content"), optional=("days",))
    title = _text(args, "title", maximum=200)
    content = _text(args, "content", maximum=20_000)
    days = _integer(args, "days", 7, 1, 30)
    sentences = [line.strip(" -*#\t") for line in re.split(r"\n+|(?<=[.!?])\s+", content) if len(line.strip(" -*#\t")) >= 12][:40]
    if not sentences:
        raise ValueError("Añade apuntes con al menos una frase de 12 caracteres para crear tarjetas basadas en tu texto.")
    cards = []
    for i, sentence in enumerate(sentences):
        concept, sep, definition = sentence.partition(":")
        if sep and 2 <= len(concept) <= 100 and definition.strip():
            front, back = f"¿Qué sabes de {concept.strip()}?", definition.strip()
        else:
            words = sentence.split()
            hidden = max(range(len(words)), key=lambda index: len(words[index]))
            answer = words[hidden]
            words[hidden] = "_____"
            front, back = "Completa: " + " ".join(words), answer
        cards.append({"number": i + 1, "front": front, "back": back, "source": sentence})
    plan = []
    for day in range(1, days + 1):
        new = [card["number"] for card in cards if (card["number"] - 1) % days == day - 1]
        review = sorted({card["number"] for card in cards if any((card["number"] - 1) % days + 1 + gap == day for gap in (1, 3, 7))})
        plan.append({"day": day, "new_cards": new, "review_cards": review, "minutes": min(60, max(10, (len(new) + len(review)) * 3))})
    markdown = f"# {title}\n\n## Tarjetas\n\n" + "\n\n".join(f"{card['number']}. {card['front']}\n   Respuesta: {card['back']}" for card in cards) + "\n\n## Plan\n\n" + "\n".join(f"- Día {row['day']}: nuevas {row['new_cards'] or 'ninguna'}; repasar {row['review_cards'] or 'ninguna'}; {row['minutes']} min." for row in plan)
    return _artifact(db, title, {"type": "study", "description": markdown, "cards": cards, "plan": plan, "method": "Tarjetas extraídas literalmente de los apuntes y repaso en los días +1, +3 y +7 dentro del periodo."}, project_id)


def files_create(db, args, project_id):
    _arguments(args, required=("title", "content"), optional=("format", "path"))
    title = _text(args, "title", maximum=200)
    content = _text(args, "content", maximum=30_000)
    extension = args.get("format", "md")
    if extension not in {"md", "txt", "html", "csv"}:
        raise ValueError("Formato permitido: md, txt, html o csv.")
    path = args.get("path", f"documents/{_slug(title)}.{extension}")
    if not isinstance(path, str) or Path(path).suffix.lower() != "." + extension:
        raise ValueError("La extensión de path debe coincidir con format.")
    if extension == "html":
        content = '<!doctype html><html lang="es"><meta charset="UTF-8"><title>' + html.escape(title) + '</title><style>body{max-width:800px;margin:40px auto;font:18px/1.7 system-ui;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}</style><h1>' + html.escape(title) + "</h1><pre>" + html.escape(content) + "</pre></html>"
    elif extension == "md":
        content = f"# {title}\n\n{content}\n"
    elif extension == "csv":
        rows = list(csv.reader(io.StringIO(content)))
        if not rows or len(rows) > 1000 or any(len(row) > 50 for row in rows):
            raise ValueError("CSV válido: máximo 1.000 filas y 50 columnas.")
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        for row in rows:
            writer.writerow(["'" + cell if cell.lstrip().startswith(("=", "+", "-", "@")) or cell.startswith(("\t", "\r")) else cell for cell in row])
        content = output.getvalue()
    written = _write(path, content)
    result = _artifact(db, title, {"type": "file", "description": f"Documento {extension.upper()} guardado en {written['path']}.", "path": written["path"], "format": extension}, project_id)
    return {**result, **written}


def calendar_list(db, args, project_id):
    _arguments(args, optional=("from", "to"))
    start = parse_instant(args["from"]) if args.get("from") else None
    end = parse_instant(args["to"]) if args.get("to") else None
    if start and end and start >= end:
        raise ValueError("El inicio del intervalo debe preceder al final.")
    rows = db.scalars(select(Item).where(Item.kind == "calendar").order_by(Item.created_at)).all()
    events = []
    for row in rows:
        if project_id and row.data.get("project_id") != project_id:
            continue
        event_start = parse_instant(row.data["start"])
        event_end = parse_instant(row.data["end"])
        if start and event_end <= start or end and event_start >= end:
            continue
        events.append({"id": row.id, "title": row.title, **row.data})
    events.sort(key=lambda event: event["start"])
    return {"events": events[:200], "truncated": len(events) > 200, "scope": "Agenda local de PABLO OS."}


def calendar_create(db, args, project_id):
    _arguments(args, required=("title", "start"), optional=("end", "description"))
    title = _text(args, "title", maximum=200)
    start = parse_instant(_text(args, "start", maximum=60))
    end = parse_instant(_text(args, "end", maximum=60)) if "end" in args else start + timedelta(hours=1)
    description = _text(args, "description", default="", maximum=5000, allow_empty=True)
    if end <= start or end - start > timedelta(days=31):
        raise ValueError("El evento debe terminar después de comenzar y durar como máximo 31 días.")
    _project(db, project_id)
    conflicts = calendar_list(db, {"from": start.isoformat(), "to": end.isoformat()}, None)["events"]
    row = Item(kind="calendar", title=title, data={"start": start.isoformat(), "end": end.isoformat(), "description": description, "project_id": project_id, "source": "local"})
    db.add(row)
    db.flush()
    return {"id": row.id, "title": title, **row.data, "conflicts": [{"id": event["id"], "title": event["title"]} for event in conflicts], "verified": True, "scope": "Evento guardado en la agenda local; no se envían invitaciones."}


def email_draft(db, args, project_id):
    _arguments(args, required=("to", "subject", "body"))
    to = _text(args, "to", maximum=254)
    subject = _text(args, "subject", maximum=200)
    body = _text(args, "body", maximum=20_000)
    if not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", to) or any(c in subject for c in "\r\n"):
        raise ValueError("Destinatario o asunto inválido.")
    return _artifact(db, subject, {"type": "email_draft", "to": to, "subject": subject, "body": body, "description": f"Para: {to}\nAsunto: {subject}\n\n{body}", "status": "DRAFT", "sent": False, "scope": "Borrador local. No se ha enviado correo."}, project_id)


def automation_create(db, args, project_id):
    _arguments(args, required=("title", "goal", "run_at"), optional=("interval_minutes", "mode"))
    title = _text(args, "title", maximum=200)
    goal = _text(args, "goal", maximum=12_000)
    instant = parse_instant(_text(args, "run_at", maximum=60))
    interval = _integer(args, "interval_minutes", 0, 0, 10080)
    mode = args.get("mode", "CHAT")
    if mode not in {"ASK", "PLAN", "DO", "RESEARCH", "CHAT"}:
        raise ValueError("Modo de automatización inválido.")
    if instant <= datetime.now(timezone.utc) or 0 < interval < 5:
        raise ValueError("Elige una fecha futura y un intervalo de al menos cinco minutos (0 para una sola vez).")
    _project(db, project_id)
    if db.scalar(select(func.count()).select_from(Schedule)) >= 100:
        raise ValueError("Máximo 100 automatizaciones por instalación.")
    row = Schedule(title=title, goal=goal, mode=mode, project_id=project_id, next_run=instant.isoformat(), interval_minutes=interval)
    db.add(row)
    db.flush()
    return {"id": row.id, "title": title, "next_run": row.next_run, "interval_minutes": interval, "mode": mode, "enabled": True, "verified": True, "scope": "El worker ejecutará el objetivo en la fecha programada mientras PABLO OS esté abierto; cada acción conserva sus aprobaciones."}


def register_workspace_tools(registry, Tool):
    for name, risk, agent, function in [
        ("workspace.list", "SAFE", "File", workspace_list),
        ("workspace.read", "SAFE", "File", workspace_read),
        ("workspace.write", "MODERATE", "Software Engineer", workspace_write),
        ("code.scaffold", "MODERATE", "Software Engineer", code_scaffold),
        ("game.scaffold", "MODERATE", "Game Dev", lambda db, args, project: code_scaffold(db, {**args, "kind": "game"}, project)),
        ("code.run", "CRITICAL", "Software Engineer", code_run),
        ("git.status", "SAFE", "GitHub", git_status),
        ("git.diff", "SAFE", "GitHub", git_diff),
        ("git.branch", "MODERATE", "GitHub", git_branch),
        ("security.audit", "SAFE", "Security", security_audit),
        ("devops.diagnose", "SAFE", "DevOps", devops_diagnose),
        ("study.create", "MODERATE", "Study", study_create),
        ("files.create", "MODERATE", "File", files_create),
        ("calendar.list", "SAFE", "Calendar", calendar_list),
        ("calendar.create", "MODERATE", "Calendar", calendar_create),
        ("email.draft", "MODERATE", "Email", email_draft),
        ("automation.create", "MODERATE", "Automation", automation_create),
    ]:
        registry.register(Tool(name, risk, agent, function))
