import pytest

from pablo.workspace_tools import workspace_write


def test_authenticated_preview_bundles_scripts_and_keeps_sandbox(client, tmp_path, monkeypatch):
    monkeypatch.setenv('PABLO_WORKSPACE_ROOT', str(tmp_path))
    for name, content in {'index.html': '<html><head><link rel="stylesheet" href="styles.css"><script src="script.js" defer></script></head><body><button>Mostrar</button></body></html>', 'styles.css': 'button {color:red}', 'script.js': 'document.querySelector("button").onclick=()=>alert("123");'}.items():
        workspace_write(None, {'path': 'web/' + name, 'content': content}, None)
    result = client.get('/api/v1/workspace/preview/web/index.html')
    assert result.status_code == 200
    assert 'button {color:red}' in result.text and 'alert("123")' in result.text
    assert result.text.index('onclick') > result.text.index('<button>')
    assert 'sandbox allow-scripts allow-modals' in result.headers['content-security-policy']
    assert 'allow-same-origin' not in result.headers['content-security-policy']
    client.cookies.clear()
    assert client.get('/api/v1/workspace/preview/web/index.html').status_code == 401


@pytest.mark.parametrize('source', ['../other/script.js', '%2e%2e/other/script.js', '/api/v1/export', 'https://example.com/script.js'])
def test_preview_rejects_script_outside_project(client, tmp_path, monkeypatch, source):
    monkeypatch.setenv('PABLO_WORKSPACE_ROOT', str(tmp_path))
    workspace_write(None, {'path': 'web/index.html', 'content': f'<script src="{source}"></script>'}, None)
    assert client.get('/api/v1/workspace/preview/web/index.html').status_code == 422
