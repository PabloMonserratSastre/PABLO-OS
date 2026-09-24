"""Generate a local-only database password, never print it."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[2]
target = root / '.env'
if target.exists():
    print('.env ya existe; no se ha modificado.')
else:
    target.write_text((root / '.env.example').read_text(encoding='utf-8').replace('POSTGRES_PASSWORD=\n', 'POSTGRES_PASSWORD=' + secrets.token_hex(32) + '\n'), encoding='utf-8')
    try:
        target.chmod(0o600)
    except OSError:
        pass
    print('Configuración local creada.')
