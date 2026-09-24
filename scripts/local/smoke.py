"""Clean-install HTTP smoke test with real API/worker processes and disposable data."""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='pablo-smoke-') as temporary:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'PYTHONPATH': str(root / 'backend'), 'DATABASE_URL': 'sqlite:///' + temporary + '/clean.db', 'APP_ORIGIN': f'http://localhost:{port}', 'AI_API_KEY': '', 'AI_EMBED_MODEL': ''}
    subprocess.run([sys.executable, '-m', 'alembic', '-c', 'backend/alembic.ini', 'upgrade', 'head'], cwd=root, env=env, check=True)
    logs = open(Path(temporary) / 'runtime.log', 'w+')
    api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'pablo.main:app', '--host', '127.0.0.1', '--port', str(port)], cwd=root, env=env, stdout=logs, stderr=logs)
    worker = subprocess.Popen([sys.executable, '-m', 'pablo.worker'], cwd=root, env=env, stdout=logs, stderr=logs)
    try:
        with httpx.Client(trust_env=False, base_url=origin, headers={'X-Pablo-Request': '1', 'Origin': origin}, timeout=5) as client:
            for _ in range(80):
                try:
                    if client.get('/ready').is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError('API failed to start')
            assert client.get('/').status_code == 200
            assert client.get('/api/v1/state').status_code == 401
            assert client.post('/api/v1/auth/setup', json={'name':'QA', 'password':secrets.token_urlsafe(24)}).status_code == 200
            profile = client.get('/api/v1/state').json()['profile']
            profile['autonomy'] = 'AUTONOMOUS'
            assert client.put('/api/v1/settings', json=profile).status_code == 200
            response = client.post('/api/v1/commands', json={'goal':'Quiero crear un videojuego', 'mode':'DO'})
            assert response.status_code == 200
            run_id = response.json()['id']
            for _ in range(120):
                state = client.get('/api/v1/state').json()
                run = next(r for r in state['runs'] if r['id'] == run_id)
                if run['status'] in {'COMPLETED','FAILED','BLOCKED'}:
                    break
                time.sleep(0.1)
            assert run['status'] == 'COMPLETED', run
            assert len([i for i in state['items'] if i['kind']=='projects']) == 1
            assert len([i for i in state['items'] if i['kind']=='tasks']) == 4
            worker.terminate()
            worker.wait(timeout=5)
            worker = subprocess.Popen([sys.executable, '-m', 'pablo.worker'], cwd=root, env=env, stdout=logs, stderr=logs)
            state = client.get('/api/v1/state').json()
            assert len([i for i in state['items'] if i['kind']=='tasks']) == 4
            assert client.post('/api/v1/documents', files={'file':('notes.md', b'Vector retrieval uses embeddings.')}).status_code == 200
            assert client.get('/api/v1/search', params={'q':'embeddings'}).json()['sources'][0]['source'] == 'notes.md'
            from datetime import datetime, timedelta, timezone
            at=(datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat()
            scheduled=client.post('/api/v1/schedules',json={'title':'Smoke scheduled briefing','goal':'Qué tengo pendiente','run_at':at})
            assert scheduled.status_code == 200, scheduled.text
            for _ in range(100):
                rows=client.get('/api/v1/schedules').json()
                if rows[0]['last_run_id']:
                    scheduled_run=client.get('/api/v1/runs/'+rows[0]['last_run_id']).json()
                    if scheduled_run['status']=='COMPLETED':
                        break
                time.sleep(0.1)
            else:
                raise AssertionError('Scheduled job did not complete')
            assert client.get('/api/v1/runtime').json()['worker']=='ONLINE'
            assert client.delete('/api/v1/items/'+scheduled_run['conversation_id']).status_code==200
            assert client.get('/api/v1/runs/'+scheduled_run['id']).status_code==404
            print('PASS: clean migrations, static frontend, authentication, real API and worker, project and dependent tasks, restart persistence, documents, scheduled execution and private-history deletion.')
    finally:
        for process in [worker, api]:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        logs.close()
        # Windows can retain SQLite handles briefly after process termination.
        for attempt in range(20):
            try:
                (Path(temporary) / 'clean.db').unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.1)
