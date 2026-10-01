"""Agenda regression scenarios; all data and provider replies are disposable."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from pablo.agenda import TOOLS, plan, validate_step
from pablo.db import DB, Item, Owner, Run
from pablo.providers import CompatibleProvider
from pablo.worker import process


def execute(client, goal):
    response = client.post('/api/v1/commands', json={'goal': goal, 'mode': 'CHAT'})
    assert response.status_code == 200, response.text
    run_id = response.json()['id']
    for _ in range(20):
        process(run_id)
        with DB() as db:
            run = db.get(Run, run_id)
            if run.status not in {'QUEUED', 'RUNNING'}:
                return run
    raise AssertionError('Run never finished')


def autonomous():
    with DB() as db:
        owner = db.get(Owner, 1)
        owner.settings = owner.settings | {'autonomy': 'AUTONOMOUS'}
        db.commit()


@pytest.mark.parametrize('word,offset', [('hoy', 0), ('mañana', 1), ('pasado mañana', 2)])
def test_homework_has_real_deadline_and_preserves_title(client, monkeypatch, word, offset):
    autonomous()
    monkeypatch.setattr(CompatibleProvider, 'request', lambda *a: pytest.fail('Simple tasks need no model quota'))
    run = execute(client, f'Añade una tarea llamada Repasar Matemáticas para {word}')
    assert run.status == 'COMPLETED', run.result
    day = (datetime.now(ZoneInfo('Europe/Madrid')).date() + timedelta(days=offset)).isoformat()
    with DB() as db:
        row = db.scalar(select(Item).where(Item.kind == 'tasks'))
        assert row.title == 'Repasar Matemáticas'
        assert row.data['due'] == day
    assert day in run.result
    process(run.id)
    assert len([i for i in client.get('/api/v1/state').json()['items'] if i['kind'] == 'tasks']) == 1


def test_tomorrow_query_does_not_show_whole_week(client):
    day = (datetime.now(ZoneInfo('Europe/Madrid')).date() + timedelta(days=1)).isoformat()
    client.post('/api/v1/items/tasks', json={'title': 'Entrega mañana', 'due': day})
    client.post('/api/v1/items/tasks', json={'title': 'Sin plazo'})
    run = execute(client, 'qué tengo mañana')
    assert run.status == 'COMPLETED'
    assert 'Entrega mañana' in run.result and 'Sin plazo' not in run.result


def test_catalog_has_no_external_actions(client):
    rows = client.get('/api/v1/tools').json()
    assert {r['id'] for r in rows} == TOOLS
    assert client.get('/api/v1/integrations/google/calendar').status_code == 404
    for tool, args in [('email.send', {}), ('google_calendar.create', {}), ('items.delete', {'kind': 'documents'})]:
        assert client.post('/api/v1/tool-runs', json={'tool': tool, 'arguments': args}).status_code == 422


def test_scope_checked_before_any_action(client, monkeypatch):
    autonomous()
    monkeypatch.setenv('AI_MODEL', 'test')
    monkeypatch.setenv('AI_API_KEY', 'test')
    monkeypatch.setattr(CompatibleProvider, 'request', lambda *a: {'choices': [{'message': {'content': json.dumps({
        'summary': 'Mixed plan', 'steps': [
            {'tool': 'tasks.create', 'arguments': {'title': 'Should not exist'}},
            {'tool': 'email.send', 'arguments': {}}]})}}]})
    run = execute(client, 'Haz una tarea y envíala')
    assert run.status == 'FAILED'
    assert not [i for i in client.get('/api/v1/state').json()['items'] if i['kind'] == 'tasks']


def test_model_receives_real_ids_and_only_agenda_catalog(client, monkeypatch):
    row = client.post('/api/v1/items/tasks', json={'title': 'Ensayo', 'due': '2030-01-01'}).json()
    autonomous()
    monkeypatch.setenv('AI_MODEL', 'test')
    monkeypatch.setenv('AI_API_KEY', 'test')
    def reply(provider, path, payload):
        context = json.loads(payload['messages'][1]['content'])['CONTEXTO_NO_CONFIABLE']
        assert context['today'] == datetime.now(ZoneInfo('Europe/Madrid')).date().isoformat()
        assert any(i['id'] == row['id'] and i['version'] == row['version'] for i in context['agenda_items'])
        catalog = json.loads(payload['messages'][0]['content'].split('CATÁLOGO ACTUAL (herramienta: argumentos):\n')[1])
        assert set(catalog) == TOOLS
        return {'choices': [{'message': {'content': json.dumps({'summary': 'Cambiar el plazo', 'steps': [
            {'tool': 'items.update', 'arguments': {'kind': 'tasks', 'id': row['id'], 'changes': {'due': '2030-01-02'}}}]})}}]}
    monkeypatch.setattr(CompatibleProvider, 'request', reply)
    run = execute(client, 'El ensayo lo entrego un día después, cámbialo')
    assert run.status == 'COMPLETED', run.result
    tasks = [i for i in client.get('/api/v1/state').json()['items'] if i['kind'] == 'tasks']
    assert len(tasks) == 1 and tasks[0]['due'] == '2030-01-02'


def test_two_projects_link_tasks_to_correct_parent(client, monkeypatch):
    autonomous()
    from pablo.schemas import Plan
    monkeypatch.setattr(CompatibleProvider, 'plan', lambda *a: (Plan(summary='Organizar trabajos', steps=[
        {'tool': 'projects.create', 'arguments': {'title': 'Historia'}},
        {'tool': 'tasks.create', 'arguments': {'title': 'Leer historia'}, 'depends_on': [0]},
        {'tool': 'projects.create', 'arguments': {'title': 'Física'}},
        {'tool': 'tasks.create', 'arguments': {'title': 'Problemas'}, 'depends_on': [2]},
    ]), {},))
    monkeypatch.setenv('AI_MODEL', 'test')
    monkeypatch.setenv('AI_API_KEY', 'test')
    run = execute(client, 'Organiza dos trabajos diferentes')
    assert run.status == 'COMPLETED', run.result
    rows = client.get('/api/v1/state').json()['items']
    by_title = {i['title']: i for i in rows if i['kind'] in {'tasks', 'projects'}}
    assert by_title['Leer historia']['project_id'] == by_title['Historia']['id']
    assert by_title['Problemas']['project_id'] == by_title['Física']['id']


def test_delete_still_requires_confirmation(client):
    autonomous()
    row = client.post('/api/v1/items/tasks', json={'title': 'Borrador'}).json()
    run = execute(client, 'Borra la tarea "Borrador"')
    assert run.status == 'WAITING_APPROVAL'
    assert any(i['id'] == row['id'] for i in client.get('/api/v1/state').json()['items'])
    approval = client.get('/api/v1/state').json()['approvals'][0]
    client.post(f'/api/v1/approvals/{approval["id"]}', json={'approve': True})
    process(run.id)
    process(run.id)
    assert not any(i['id'] == row['id'] for i in client.get('/api/v1/state').json()['items'])


def test_one_format_repair_before_saving(client, monkeypatch):
    autonomous()
    monkeypatch.setenv('AI_MODEL', 'test')
    monkeypatch.setenv('AI_API_KEY', 'test')
    calls = []
    def reply(*args):
        calls.append(True)
        content = 'Not JSON' if len(calls) == 1 else json.dumps({'summary': 'Guardar deberes', 'steps': [{'tool': 'tasks.create', 'arguments': {'title': 'Deberes de química'}}]})
        return {'choices': [{'message': {'content': content}}]}
    monkeypatch.setattr(CompatibleProvider, 'request', reply)
    run = execute(client, 'Me han puesto ejercicios de química, apúntalos')
    assert run.status == 'COMPLETED', run.result
    assert len(calls) == 2 and run.usage['format_repaired']
    tasks = [i for i in client.get('/api/v1/state').json()['items'] if i['kind'] == 'tasks']
    assert len(tasks) == 1 and tasks[0]['title'] == 'Deberes de química'


def test_name_lookup_accepts_case_and_accents_without_guessing(client):
    from pablo.item_tools import update_item
    row = client.post('/api/v1/items/tasks', json={'title': 'Repasar Matemáticas'}).json()
    with DB() as db:
        result = update_item(db, {'kind': 'tasks', 'title': 'repasar matematicas', 'changes': {'status': 'DONE'}}, None)
        assert result['id'] == row['id']
        with pytest.raises(ValueError, match='único'):
            update_item(db, {'kind': 'tasks', 'title': 'matematicas', 'changes': {'status': 'DONE'}}, None)


@pytest.mark.parametrize('goal', ['Crea una tarea llamada Pan para mañana y borra otra', 'Crea una tarea llamada Pan para mañana. No ejecutes nada'])
def test_extra_instructions_go_to_model(goal):
    assert plan(goal, 'CHAT') is None


def test_retired_google_command_is_explained():
    result = plan('qué eventos tengo mañana en el calendario', 'CHAT')
    assert not result.steps and 'tareas y proyectos' in result.summary
    with pytest.raises(ValueError):
        validate_step({'tool': 'items.create', 'arguments': {'kind': 'memory'}})
