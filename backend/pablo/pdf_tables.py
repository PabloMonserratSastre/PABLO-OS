"""Keep table coordinates and repeated row context instead of flattening columns."""
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from io import BytesIO

MARKER = '[PDF estructurado v1]'
RECORD = '[Horario] '
DAYS = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
DISPLAY_DAYS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
SCHEDULE_WORDS = r'asignatura|clase|periodo|cuatri|semestre|tabla s[12]|horario|\bs[12]\b'


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


def timetable_answer(db, goal, history, project_id=None, today=None):
    from sqlalchemy import select

    from .db import Chunk, Item
    query = normalized(goal)
    user_history = [normalized(row.get('content', '')) for row in history if row.get('role') == 'user']
    if re.search(r'\b(crea|crear|borra|elimina|modifica|guarda|envia|anade|programa)\b', query):
        return None
    days = [day for day in DAYS if re.search(r'\b' + day + r'\b', query)]
    relative_label = None
    relative_date = None
    try:
        base_date = date.fromisoformat(today) if today else date.today()
    except ValueError:
        base_date = date.today()
    if re.search(r'\bpasado manana\b', query):
        relative_label, relative_date = 'Pasado mañana', base_date + timedelta(days=2)
    elif re.search(r'\bmanana\b', query):
        relative_label, relative_date = 'Mañana', base_date + timedelta(days=1)
    elif re.search(r'\bhoy\b', query):
        relative_label, relative_date = 'Hoy', base_date
    elif re.search(r'\bayer\b', query):
        relative_label, relative_date = 'Ayer', base_date - timedelta(days=1)
    if relative_date:
        days = [DAYS[relative_date.weekday()]]
    history_text = ' '.join([query, *user_history[-3:]])
    if (not re.search(SCHEDULE_WORDS, query)
            and not re.fullmatch(r'[¿]?(?:(?:dime|ahora|y|solo|que tengo)\s+)*(?:los |el )?(?:' + '|'.join(DAYS) + r')[?!. ]*', query.strip())
            and not (relative_date and re.search(SCHEDULE_WORDS, history_text))):
        return None
    if not re.search(SCHEDULE_WORDS, history_text):
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
    all_records = []
    for chunk, doc in db.execute(statement):
        try:
            row = json.loads(chunk.text[len(RECORD):])
        except ValueError:
            continue
        all_records.append((row, doc))
    if not all_records:
        return None
    if not requested and len({r['periodo'] for r, _ in all_records}) > 1:
        return '¿Te refieres al primer cuatrimestre (S1) o al segundo (S2)?'
    period_records = [(row, doc) for row, doc in all_records if not requested or row['periodo'].upper() == requested]
    if not period_records:
        label = requested or 'el periodo solicitado'
        return f'No encontré asignaturas para {label} dentro de los horarios indexados.'
    if len({doc.id for _, doc in period_records}) > 1:
        return 'He encontrado varios horarios. Indica qué documento quieres consultar: ' + ', '.join(sorted({doc.title for _, doc in period_records})) + '.'
    selected_days = days or DAYS
    records = [(row, doc) for row, doc in period_records if row['dia'] in selected_days]
    semester = period_records[0][0]['periodo']
    semester_name = 'Primer cuatrimestre' if semester.upper() == 'S1' else 'Segundo cuatrimestre'
    if relative_date:
        date_text = f'{DISPLAY_DAYS[relative_date.weekday()]} {relative_date.day} de {MONTHS[relative_date.month - 1]}'
        lines = [f'📅 **{relative_label}, {date_text}**', f'Estas son tus clases del {semester_name.lower()} ({semester.upper()}):']
    else:
        lines = [f'📅 **Tu horario · {semester_name} ({semester.upper()})**']
    found = False

    def minutes(value):
        parsed = datetime.strptime(value, '%H:%M')
        return parsed.hour * 60 + parsed.minute

    def clock(value):
        return f'{value // 60:02d}:{value % 60:02d}'

    for day in selected_days:
        rows = [row for row, _ in records if row['dia'] == day and row.get('asignatura')]
        if not rows:
            if days:
                lines.extend(['', f'**{day.capitalize()}**', 'Sin clases registradas.'])
            continue
        found = True
        rows.sort(key=lambda row: minutes(row['hora']))
        starts = [minutes(row['hora']) for row in rows]
        differences = [b - a for a, b in zip(starts, starts[1:]) if 0 < b - a <= 180]
        step = Counter(differences).most_common(1)[0][0] if differences else 60
        groups = []
        for row in rows:
            start = minutes(row['hora'])
            room = row.get('cabecera', '').split('-', 1)[1].strip() if '-' in row.get('cabecera', '') else ''
            if normalized(room) in {'tbd', 'pendiente', 'por determinar', 'sin aula'}:
                room = ''
            if groups and groups[-1]['subject'] == row['asignatura'] and groups[-1]['room'] == room and start == groups[-1]['end']:
                groups[-1]['end'] = start + step
            else:
                groups.append({'start': start, 'end': start + step, 'subject': row['asignatura'], 'room': room})
        day_label = DISPLAY_DAYS[DAYS.index(day)].capitalize()
        lines.extend(['', f'**{day_label}**'])
        for group in groups:
            room = f" · Aula {group['room']}" if group['room'] else ''
            lines.append(f"• **{clock(group['start'])}–{clock(group['end'])}** · {group['subject']}{room}")
    if not found:
        lines.append('\nNo tienes clases registradas para ese día.')
    source_records = records or period_records
    pages = ', '.join(str(page) for page in sorted({row['pagina'] for row, _ in source_records}))
    lines.extend(['', f'**Fuente:** {source_records[0][1].title} · página {pages}.'])
    return '\n'.join(lines)
