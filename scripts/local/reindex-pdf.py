"""Re-extract an existing document from its original PDF, backing up the old index."""
import json
import os
import sys
from pathlib import Path
from run import ROOT, load_environment

os.chdir(ROOT)
load_environment()
sys.path.insert(0, str(ROOT / 'backend'))
from sqlalchemy import delete, select
from pablo.db import DB, Chunk, Item, audit, now
from pablo.knowledge import extract_isolated, index
from pablo.pdf_tables import timetable_answer

document_id, original = sys.argv[1], Path(sys.argv[2])
with DB() as db:
    doc = db.get(Item, document_id)
    if not doc or doc.kind != 'documents' or doc.title != original.name:
        raise SystemExit('The original filename must match the selected document.')
    version = doc.version
content = extract_isolated(original.name, original.read_bytes())
with DB() as db:
    doc = db.get(Item, document_id)
    if doc.version != version:
        raise SystemExit('Document changed; no update applied.')
    old = db.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.position)).all()
    backup = {'id': doc.id, 'title': doc.title, 'version': doc.version, 'data': doc.data, 'chunks': [{'position': row.position, 'text': row.text, 'embedding': row.embedding} for row in old]}
    backup_path = ROOT / '.local' / ('document-before-tables-' + document_id + '-' + now().replace(':', '-') + '.json')
    backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding='utf-8')
    db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    count = index(db, document_id, content)
    doc.data = doc.data | {'chunks': count, 'status': 'INDEXED', 'description': content[:500]}
    doc.version += 1
    doc.updated_at = now()
    audit(db, 'document.reextracted', document_id=doc.id, chunks=count)
    db.commit()
    print(json.dumps({'chunks': count, 'answer': timetable_answer(db, 'que asignaturas tengo los lunes en el segundo cuatrimestre', [])}, ensure_ascii=True))
