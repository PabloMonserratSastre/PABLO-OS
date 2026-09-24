"""Local supervisor. One process owns the API and worker for this installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local'


def load_environment():
    os.chdir(ROOT)
    if (ROOT / '.env').exists():
        for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    os.environ['PYTHONPATH'] = str(ROOT / 'backend')
    os.environ.setdefault('DATABASE_URL', 'sqlite:///' + str(ROOT / 'pablo.db'))
    os.environ['PABLO_INSTALLATION_ID'] = hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:20]


def health(port):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/ready', timeout=2) as response:
            data = json.load(response)
        return data.get('application') == 'pablo-os' and data.get('installation') == os.environ['PABLO_INSTALLATION_ID']
    except (OSError, ValueError):
        return False


def acquire_lock():
    handle = open(LOCAL / 'supervisor.lock', 'a+b')
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt
        if not handle.read(1):
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    load_environment()
    LOCAL.mkdir(exist_ok=True)
    state_file = LOCAL / 'runtime.json'
    if args.stop:
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding='utf-8'))
            (LOCAL / 'stop.request').write_text(state['token'], encoding='utf-8')
            print('Cierre solicitado. Los datos estan guardados.')
        else:
            print('PABLO OS ya esta detenido.')
        return 0
    try:
        lock = acquire_lock()
    except OSError:
        print('PABLO OS ya esta arrancado o iniciandose.')
        return 0
    if not (ROOT / 'dist-local' / 'index.html').is_file():
        raise SystemExit('Falta la interfaz compilada: ejecuta npm run build:local.')
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', args.port))
        except OSError:
            if health(args.port):
                return 0
            raise SystemExit(f'El puerto {args.port} esta ocupado por otra aplicacion.')
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    subprocess.run([sys.executable, '-m', 'alembic', '-c', 'backend/alembic.ini', 'upgrade', 'head'], check=True, **flags)
    children = []
    stopped = False
    token = uuid.uuid4().hex
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        for command in [['-m', 'pablo.worker'], ['-m', 'uvicorn', 'pablo.main:app', '--host', '127.0.0.1', '--port', str(args.port)]]:
            children.append(subprocess.Popen([sys.executable, *command], **flags))
        state_file.write_text(json.dumps({'supervisor': os.getpid(), 'children': [c.pid for c in children], 'token': token, 'port': args.port}), encoding='utf-8')
        print(f'PABLO OS: http://localhost:{args.port}', flush=True)
        while not stopped:
            request = LOCAL / 'stop.request'
            if request.exists() and request.read_text(encoding='utf-8') == token:
                request.unlink(missing_ok=True)
                break
            for child in children:
                if child.poll() is not None:
                    print('Un componente se ha detenido; se cerrara la instalacion.', flush=True)
                    return child.returncode or 1
            time.sleep(0.3)
    finally:
        for child in children:
            if child.poll() is None:
                if os.name == 'nt':
                    subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32' / 'taskkill.exe'), '/PID', str(child.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, **flags)
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        state_file.unlink(missing_ok=True)
        lock.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
