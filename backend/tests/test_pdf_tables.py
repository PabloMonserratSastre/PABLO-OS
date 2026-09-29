import json
import pytest
from sqlalchemy import select
from pablo.db import DB, Chunk, Item
from pablo.knowledge import index, restore_text
from pablo.pdf_tables import MARKER, RECORD, table_blocks, timetable_answer
from pablo.providers import CompatibleProvider
from test_flows import run_until_pause


def timetable():
    blocks = [MARKER]
    for period, names in [('S1', ['Sistemas', 'Redes']), ('S2', ['Escritura técnica', 'Videojuegos'])]:
        rows = [[period, 'LUNES - tbd', 'MARTES - tbd', 'VIERNES - tbd'], ['15:00', names[0], 'Otra materia', ''], ['16:00', names[0], 'Otra materia', ''], ['17:00', names[1], 'Otra materia', ''], ['18:00', names[1], 'Otra materia', '']]
        blocks.extend(table_blocks(rows, 1, 1 if period == 'S1' else 2))
    return '\n\n'.join(blocks)


@pytest.fixture
def document(client):
    with DB() as db:
        doc = Item(kind='documents', title='Horario de prueba.pdf', data={'project_id': None})
        db.add(doc); db.flush()
        index(db, doc.id, timetable())
        db.commit()
        return doc.id


@pytest.mark.parametrize('goal', ['qué asignaturas tengo los lunes en el segundo cuatri', 'dime que asignaturas tengo los lunes tabla S2', 'ahora los lunes el segundo cuatrimestre', '¿Qué clases tengo los lunes del 2º cuatrimestre?', 'dime en el periodo S2 que tengo los lunes'])
def test_second_semester_answer_uses_cells_not_tbd(client, document, monkeypatch, goal):
    monkeypatch.setattr(CompatibleProvider, 'request', lambda *a: pytest.fail('Exact timetable reading must not ask the model to infer columns'))
    row = client.post('/api/v1/commands', json={'goal': goal, 'mode': 'CHAT'}).json()
    run = run_until_pause(row['id'])
    assert run.status == 'COMPLETED', run.result
    assert 'Escritura técnica' in run.result and 'Videojuegos' in run.result
    assert '15:00–17:00' in run.result and '17:00–19:00' in run.result
    assert 'Sistemas' not in run.result and 'tbd' not in run.result and 'JSON' not in run.result
    assert '📅' in run.result and '**Fuente:**' in run.result


def test_reindex_preserves_structured_cells(client, document):
    response = client.post(f'/api/v1/documents/{document}/reindex')
    assert response.status_code == 200, response.text
    with DB() as db:
        chunks = db.scalars(select(Chunk).where(Chunk.document_id == document).order_by(Chunk.position)).all()
        assert restore_text(chunks) == timetable()
        assert 'Videojuegos' in timetable_answer(db, 'lunes segundo cuatri', [], None)


def test_followup_uses_user_period_not_wrong_assistant(client, document):
    history = [{'role':'user', 'content':'asignaturas del segundo cuatrimestre'}, {'role':'assistant', 'content':'S1 no hay asignaturas'}]
    with DB() as db:
        result = timetable_answer(db, 'y los lunes?', history)
        assert 'S2' in result and 'Videojuegos' in result
        assert timetable_answer(db, 'qué tiempo hará el lunes', history) is None
        assert timetable_answer(db, 'crea un evento el lunes segundo cuatri', history) is None


def test_missing_semester_and_empty_day(client, document):
    with DB() as db:
        assert '¿Te refieres' in timetable_answer(db, 'que asignaturas tengo los lunes', [])
        assert 'No aparecen asignaturas' in timetable_answer(db, 'que asignaturas tengo los viernes S2', [])


def test_whole_period_is_presented_by_day(client, document):
    with DB() as db:
        result = timetable_answer(db, 'dime mi horario del periodo S1', [])
    assert '**Lunes**' in result and '**Martes**' in result
    assert '15:00–17:00' in result and 'Sistemas' in result
    assert '[Horario]' not in result


def test_header_preamble_does_not_merge_tables():
    rows = [['INICIO', None, None], ['S1', 'LUNES - 406', 'MARTES - 406'], ['15:00', 'Asignatura\npartida', 'Otra']]
    records = [json.loads(block[len(RECORD):]) for block in table_blocks(rows, 2, 3)]
    assert records[0]['periodo'] == 'S1' and records[0]['asignatura'] == 'Asignatura partida'
    assert records[0]['dia'] == 'lunes' and records[1]['dia'] == 'martes'


def test_non_timetable_with_weekdays_is_not_discarded():
    result = list(table_blocks([['Grupo', 'Lunes', 'Martes'], ['Ventas', '15', '20']], 1, 1))
    assert result and 'Ventas' in result[0] and 'Lunes: 15' in result[0]
