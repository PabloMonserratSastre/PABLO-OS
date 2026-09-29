"""A concise digest from verified Google data, with local-day boundaries."""
import re
from datetime import datetime, time, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo

GOAL = "Preparar mi resumen diario"


def clean(value, limit=95):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = re.sub(r"[<>`*\[\]#]", "", value)
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def digest(db, args, project_id):
    from .db import Owner
    from .integrations import _google, email_list
    owner = db.get(Owner, 1)
    zone = ZoneInfo(owner.settings.get("timezone", "Europe/Madrid"))
    today = datetime.now(zone).date()
    start = datetime.combine(today, time.min, zone)
    end = datetime.combine(today + timedelta(days=1), time.min, zone)
    mail = email_list(db, {"query": "in:inbox", "limit": 10}, None)
    events, page = [], None
    for _ in range(10):
        params = {"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
        if page:
            params["pageToken"] = page
        result = _google(db, "calendar", "GET", "calendars/primary/events", params=params)
        events.extend(e for e in result.get("items", []) if e.get("status") != "cancelled")
        page = result.get("nextPageToken")
        if not page:
            break
    lines = [f"Hola {clean(owner.name, 40)}, este es tu resumen diario.", "",
             f"**Tus últimos {len(mail['messages'])} correos**", ""]
    for message in mail["messages"]:
        name, address = parseaddr(message.get("from", ""))
        sender = name or address.split('@')[0] or "Remitente desconocido"
        lines.append(f"- **{clean(sender, 35)}:** {clean(message.get('subject') or 'Sin asunto', 85)}")
    if not mail["messages"]:
        lines.append("No hay correos en tu bandeja de entrada.")
    lines.extend(["", "**Tu calendario de hoy**", ""])
    for event in events[:12]:
        begin = event.get("start", {})
        when = "Todo el día" if begin.get("date") else datetime.fromisoformat(begin["dateTime"].replace("Z", "+00:00")).astimezone(zone).strftime("%H:%M")
        lines.append(f"- **{when}** · {clean(event.get('summary') or 'Sin título', 80)}")
    if not events:
        lines.append("Hoy no tienes eventos programados.")
    elif len(events) > 12 or page:
        lines.append("Hay más eventos; puedes consultarlos en Calendario.")
    return {"text": "\n".join(lines), "date": today.isoformat(), "timezone": str(zone)}
