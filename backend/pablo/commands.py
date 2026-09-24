"""Exact, narrow commands: preserve literal names without asking an LLM to copy them."""
import re
import unicodedata

from .schemas import Plan


def explicit_plan(goal: str, mode: str, timezone: str = "Europe/Madrid") -> Plan | None:
    if mode not in {"DO", "PLAN", "CHAT"}:
        return None
    text = goal.strip()
    # Normalize only read-only queries. Never alter literal names in writes.
    query = ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if not unicodedata.combining(c))
    query = re.sub(r'\s+', ' ', query).strip(' ¿?¡!.')
    query = re.sub(r'^(?:(?:hola|buenas|oye)[, ]+)?(?:por favor[, ]+)?', '', query)
    query = re.sub(r'[, ]+(?:por favor|porfa|por favor gracias|gracias)$', '', query).strip(' ,')
    query = re.sub(r'^(?:puedes|podrias|puede|podria)\s+(?:decirme|mostrarme|consultar)\s+', 'dime ', query)
    query = re.sub(r'^(consulta|muestra|muestrame) por favor ', r'\1 ', query)
    calendar_query = re.sub(r', solo los eventos de ese dia$', '', query)
    calendar = re.fullmatch(
        r"(?:dime )?(?:que eventos tengo|que tengo|(?:muestra|muestrame|consulta) (?:mi agenda(?: de google)?|mis eventos|el calendario)) (?:(?:para |del |el |de )?(?:proximo |este )?)?(hoy|manana|pasado manana|ayer|lunes|martes|miercoles|jueves|viernes|sabado|domingo)(?: en (?:mi |el )?(?:calendario(?: de google)?|google calendar))?",
        calendar_query,
    )
    if calendar:
        from datetime import datetime, time, timedelta
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(timezone)
        today = datetime.now(zone).date()
        relative = {"hoy": 0, "manana": 1, "pasado manana": 2, "ayer": -1}
        weekdays = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
        word = calendar.group(1)
        offset = relative[word] if word in relative else (weekdays.index(word) - today.weekday()) % 7
        if word in weekdays and offset == 0 and "proximo " in calendar_query:
            offset = 7
        day = today + timedelta(days=offset)
        start = datetime.combine(day, time.min, zone)
        end = datetime.combine(day + timedelta(days=1), time.min, zone)
        return Plan(summary=f"Tu agenda de Google Calendar para el {day.strftime('%d/%m/%Y')}.",
                    steps=[{"tool": "google_calendar.list", "arguments": {"start": start.isoformat(), "end": end.isoformat(), "limit": 100}}])
    listing = re.fullmatch(r"(?:dime |muestra |muestrame |lista |consulta )?(?:que |las |los |mis )?(tareas y proyectos|proyectos y tareas|tareas|proyectos)(?: pendientes)?(?: que tengo| tengo)?(?: pendientes)?", query)
    if listing:
        kinds = listing.group(1).lower()
        steps = []
        if "tareas" in kinds:
            steps.append({"tool": "tasks.list", "arguments": {}})
        if "proyectos" in kinds:
            steps.append({"tool": "projects.list", "arguments": {"pending": True}})
        return Plan(summary="Estos son tus elementos pendientes.", steps=steps)
    if re.fullmatch(r"(?:dime )?(?:que dia es hoy|a que fecha estamos|que fecha es hoy)", query):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo(timezone))
        return Plan(summary=f"Hoy es {today.strftime('%d/%m/%Y')} ({timezone}).", steps=[])
    from .daily_digest import GOAL
    if text == GOAL:
        return Plan(summary="Resumen diario", steps=[{"tool": "daily.summary", "arguments": {}}])
    if re.fullmatch(r"(?:dame|prepara|preparame|muestra|muestrame) (?:mi|el) resumen (?:diario|de hoy)", query):
        return Plan(summary="Resumen diario", steps=[{"tool": "daily.summary", "arguments": {}}])
    if mode == "PLAN":
        text = re.sub(r"[.]?\s+No (?:la|lo) ejecutes[.]?$", "", text, flags=re.I)
    gmail = re.fullmatch(
        r"(?:busca|buscar|consulta|consultar|muestra|muéstrame)\s+(?:mis |los )?correos"
        r"(?: recibidos)?\s+(?:en |de )Gmail\s+de los últimos\s+(\d{1,3})\s+días"
        r"(?: y muéstrame sus asuntos)?[.]?(?:\s+No envíes nada[.]?)?",
        text, re.I,
    )
    if gmail and 1 <= int(gmail.group(1)) <= 365:
        days = int(gmail.group(1))
        return Plan(summary=f"Consultar Gmail: correos recibidos de los últimos {days} días.",
                    steps=[{"tool": "email.list", "arguments": {
                        "query": f"in:inbox newer_than:{days}d"}, "depends_on": []}])
    batch = re.fullmatch(
        r"(?:crea|crear|añade|añádeme|añadir|agrega|agregar|apunta)(?:\s+como)?\s+(?:estas\s+|las siguientes\s+)?tareas\s*(?::|\n)\s*(.+)",
        text, re.I | re.S,
    )
    if batch and re.search(r"\b(?:no (?:crees|crear|ejecutes|ejecutar|anadas|guardes)|sin (?:crear|ejecutar|guardar))\b", query):
        return None
    if batch:
        raw = batch.group(1)
        titles = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", part).strip()
                  for part in re.split(r"\n|;|,", raw)]
        titles = [title for title in titles if title]
        if not 1 <= len(titles) <= 8 or any(len(title) > 300 for title in titles):
            raise ValueError("Indica entre 1 y 8 tareas por petición, con títulos de hasta 300 caracteres.")
        return Plan(summary=f"Crear {len(titles)} tareas con los títulos indicados.", steps=[
            {"tool": "tasks.create", "arguments": {"title": title}, "depends_on": []} for title in titles])
    kinds = {"tarea": "tasks", "proyecto": "projects", "recuerdo": "memory", "workflow": "workflows",
             "evento": "calendar", "documento": "documents", "informe": "artifacts", "borrador": "drafts"}
    action = re.fullmatch(r'(elimina|borra|completa|termina)\s+(?:la |el )?(' + "|".join(kinds) + r')\s+["“](.+?)["”][.]?', text, re.I)
    if action:
        verb, kind, title = action.groups()
        args = {"kind": kinds[kind.lower()], "title": title}
        if verb.lower() in {"completa", "termina"}:
            if kind.lower() != "tarea":
                return None
            args["changes"] = {"status": "DONE"}
            tool = "items.update"
        else:
            tool = "items.delete"
        return Plan(summary=f"{verb.capitalize()} {kind}: {title}", steps=[{"tool": tool, "arguments": args}])
    rename = re.fullmatch(r'(?:renombra|cambia el nombre de)\s+(?:la |el )?(' + "|".join(kinds) + r')\s+["“](.+?)["”]\s+a\s+["“](.+?)["”][.]?', text, re.I)
    if rename:
        kind, title, replacement = rename.groups()
        return Plan(summary=f"Renombrar {title} a {replacement}", steps=[{"tool": "items.update", "arguments": {
            "kind": kinds[kind.lower()], "title": title, "changes": {"title": replacement}}}])
    match = re.fullmatch(
        r"(?:crea|crear|añade|añadir|agrega|agregar|propón crear)\s+(?:una?\s+)?"
        r"(tarea|proyecto)\s+(?:titulad[oa]|llamad[oa]|con (?:el )?título)\s+(.+?)[.]?",
        text, re.I,
    )
    if not match:
        return None
    kind, title = match.groups()
    quoted = len(title) >= 2 and (title[0], title[-1]) in {('"', '"'), ('“', '”'), ("'", "'")}
    if quoted:
        title = title[1:-1]
    elif re.search(r"[\n.;:]|\s(?:y|pero|con|para|que|sin|mañana|hoy)\s", title, re.I):
        return None  # Additional instructions need interpretation, never silently discard them.
    if not title.strip() or len(title) > 300:
        return None
    tool = "tasks.create" if kind.casefold() == "tarea" else "projects.create"
    return Plan(summary=f"Crear {kind.casefold()}: {title}",
                steps=[{"tool": tool, "arguments": {"title": title}, "depends_on": []}])
