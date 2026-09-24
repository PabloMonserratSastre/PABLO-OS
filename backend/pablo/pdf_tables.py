"""Keep table coordinates and repeated row context instead of flattening columns."""
import json
import re
import unicodedata
from io import BytesIO

MARKER = '[PDF estructurado v1]'
RECORD = '[Horario] '
DAYS = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))


def table_blocks(rows, page, number):
    rows = [[' '.join((cell or '').split()) for cell in row] for row in rows]
    header_index = next((i for i, row in enumerate(rows) if sum(any(day in normalized(cell) for day in DAYS) for cell in row) >= 2), None)
    if header_index is not None and any(row and re.fullmatch(r'\d{1,2}:\d{2}', row[0]) for row in rows[header_index + 1:]):
        header = rows[header_index]
        semester = header[0]
        for row in rows[header_index + 1:]:
            if not row or not re.fullmatch(r'\d{1,2}:\d{2}', row[0]):
                continue
            for column, label in enumerate(header[1:], 1):
                day = next((d for d in DAYS if re.search(r'\b' + d + r'\b', normalized(label))), None)
                if day and column < len(row):
                    yield RECORD + json.dumps({'pagina': page, 'tabla': number, 'periodo': semester, 'dia': day, 'cabecera': label, 'hora': row[0], 'asignatura': row[column]}, ensure_ascii=False)
        return
    nonempty = [row for row in rows if any(row)]
    if not nonempty:
        return
    header = nonempty[0]
    for index, row in enumerate(nonempty[1:] or nonempty, 1):
        yield f'Página {page} · Tabla {number} · Fila {index}\n' + '\n'.join(f'{header[i] or "Columna " + str(i+1) if i < len(header) else "Columna " + str(i+1)}: {value or "(vacío)"}' for i, value in enumerate(row))


def extract_pdf(data):
    import pdfplumber
    blocks = []
    with pdfplumber.open(BytesIO(data)) as document:
        if len(document.pages) > 200:
            raise ValueError('Máximo 200 páginas por documento.')
        for page_number, page in enumerate(document.pages, 1):
            tables = page.find_tables()
            meaningful = [table for table in tables if any(any(cell for cell in row) for row in table.extract())]
            # Exclude table glyphs from ordinary text to avoid contradictory flattened copies.
            def outside(obj):
                x = (obj.get('x0', 0) + obj.get('x1', 0)) / 2
                y = (obj.get('top', 0) + obj.get('bottom', 0)) / 2
                return not any(t.bbox[0] <= x <= t.bbox[2] and t.bbox[1] <= y <= t.bbox[3] for t in meaningful)
            text = page.filter(outside).extract_text() or ''
            if text.strip():
                blocks.append(f'Página {page_number}\n{text}')
            for number, table in enumerate(meaningful, 1):
                blocks.extend(table_blocks(table.extract(), page_number, number))
    if not blocks:
        return ''
    return MARKER + '\n\n' + '\n\n'.join(blocks)


def timetable_answer(db, goal, history, project_id=None):
    from sqlalchemy import select
    from .db import Chunk, Item
    query = normalized(goal)
    user_history = [normalized(row.get('content', '')) for row in history if row.get('role') == 'user']
    if re.search(r'\b(crea|crear|borra|elimina|modifica|guarda|envia|anade|programa)\b', query):
        return None
    days = [day for day in DAYS if re.search(r'\b' + day + r'\b', query)]
    if not re.search(r'asignatura|clase|cuatri|semestre|tabla s[12]|horario', query) and not re.fullmatch(r'[¿]?(?:(?:dime|ahora|y|solo|que tengo)\s+)*(?:los |el )?(?:' + '|'.join(DAYS) + r')[?!. ]*', query.strip()):
        return None
    if len(days) != 1 or not re.search(r'asignatura|clase|cuatri|semestre|tabla s[12]|horario', ' '.join([query, *user_history[-3:]])):
        return None
    def period(text):
        match = re.search(r'\bs([12])\b|\b(primer|primero|segundo|1[ºo]?|2[ºo]?)\s*(?:cuatri\w*|semestre)', text)
        if not match:
            return None
        return 'S' + (match[1] or ('1' if match[2] in {'primer', 'primero', '1', '1º', '1o'} else '2'))
    requested = period(query) or next((p for text in reversed(user_history) if (p := period(text))), None)
    statement = select(Chunk, Item).join(Item, Chunk.document_id == Item.id).where(Chunk.text.startswith(RECORD))
    if project_id:
        statement = statement.where(Item.data['project_id'].as_string() == project_id)
    records = []
    for chunk, doc in db.execute(statement):
        try:
            row = json.loads(chunk.text[len(RECORD):])
        except ValueError:
            continue
        if row['dia'] == days[0] and (not requested or row['periodo'].upper() == requested):
            records.append((row, doc))
    if not records:
        return None
    if not requested and len({r['periodo'] for r, _ in records}) > 1:
        return '¿Te refieres al primer cuatrimestre (S1) o al segundo (S2)?'
    if len({doc.id for _, doc in records}) > 1:
        return 'He encontrado varios horarios. Indica qué documento quieres consultar: ' + ', '.join(sorted({doc.title for _, doc in records})) + '.'
    subjects = {}
    for row, _ in sorted(records, key=lambda pair: pair[0]['hora']):
        if row['asignatura']:
            subjects.setdefault(row['asignatura'], []).append(row['hora'])
    semester = records[0][0]['periodo']
    lines = [f'**{days[0].capitalize()} · {semester}**']
    lines.extend(f'• {subject} — {" y ".join(dict.fromkeys(hours))}.' for subject, hours in subjects.items())
    if not subjects:
        lines.append('No aparecen asignaturas en las casillas de ese día.')
    lines.append(f'Fuente: {records[0][1].title}, página {records[0][0]["pagina"]}, tabla {semester}.')
    return '\n\n'.join(lines)
