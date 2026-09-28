"""Deterministic, fast daily briefing derived from the user's own state."""

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


OPEN_TASKS = {"TODO", "PLANNED", "IN_PROGRESS", "WAITING_APPROVAL", "BLOCKED", "TESTING"}


def _local_day(value: str, zone: ZoneInfo) -> date | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed.astimezone(zone).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def build_pulse(items: list[dict], runs: list[dict], approval_count: int, timezone: str, name: str) -> dict:
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    current = datetime.now(zone)
    today = current.date()
    tasks = [row for row in items if row.get("kind") == "tasks" and row.get("status", "TODO") in OPEN_TASKS]
    overdue = [row for row in tasks if (day := _local_day(row.get("due", ""), zone)) and day < today]
    due_today = [row for row in tasks if _local_day(row.get("due", ""), zone) == today]
    high = [row for row in tasks if row.get("priority") == "HIGH"]
    blocked = [row for row in tasks if row.get("status") == "BLOCKED"]
    failed = [row for row in runs[:20] if row.get("status") == "FAILED"]

    score = max(12, 100 - min(48, len(overdue) * 12) - min(18, approval_count * 6) - min(15, len(blocked) * 8) - min(12, len(failed) * 3))
    if score >= 88:
        label, tone = "En calma", "calm"
    elif score >= 68:
        label, tone = "Con foco", "focus"
    else:
        label, tone = "Pide atención", "attention"

    if approval_count:
        headline = f"Tienes {approval_count} decisión{'es' if approval_count != 1 else ''} esperando tu revisión."
        next_action = {"title": "Revisar lo pendiente", "detail": "Decide qué cambios pueden continuar.", "destination": "Actividad"}
    elif overdue:
        headline = f"Hay {len(overdue)} tarea{'s' if len(overdue) != 1 else ''} que conviene recuperar."
        next_action = {"title": overdue[0]["title"], "detail": "Es el mejor punto para volver a tomar impulso.", "destination": "Tareas"}
    elif due_today:
        headline = f"Hoy tienes {len(due_today)} prioridad{'es' if len(due_today) != 1 else ''} con fecha marcada."
        next_action = {"title": due_today[0]["title"], "detail": "Empieza por aquí y deja que el resto se ordene.", "destination": "Tareas"}
    elif tasks:
        candidate = (high or tasks)[0]
        headline = "Tu espacio está en orden. Elige una cosa y avanza."
        next_action = {"title": candidate["title"], "detail": "Una prioridad clara vale más que diez abiertas.", "destination": "Tareas"}
    else:
        headline = "Todo despejado. Es un buen momento para pensar en grande."
        next_action = {"title": "Diseñar el próximo objetivo", "detail": "Cuéntame qué quieres conseguir y lo convertimos en pasos.", "prompt": "Ayúdame a elegir y preparar mi próximo objetivo."}

    signals = []
    if overdue:
        signals.append({"kind": "overdue", "title": f"{len(overdue)} fuera de fecha", "detail": overdue[0]["title"], "destination": "Tareas"})
    if approval_count:
        signals.append({"kind": "approval", "title": f"{approval_count} por aprobar", "detail": "Cambios esperando tu decisión", "destination": "Actividad"})
    if blocked:
        signals.append({"kind": "blocked", "title": f"{len(blocked)} bloqueada{'s' if len(blocked) != 1 else ''}", "detail": blocked[0]["title"], "destination": "Tareas"})
    if due_today:
        signals.append({"kind": "today", "title": f"{len(due_today)} para hoy", "detail": due_today[0]["title"], "destination": "Tareas"})
    if failed:
        signals.append({"kind": "failed", "title": f"{len(failed)} ejecución{'es' if len(failed) != 1 else ''} a revisar", "detail": failed[0]["goal"], "destination": "Actividad"})
    if not signals:
        signals.append({"kind": "clear", "title": "Sin alertas", "detail": "Todo funciona con normalidad"})

    greeting = "Buenos días" if current.hour < 13 else "Buenas tardes" if current.hour < 20 else "Buenas noches"
    return {
        "generated_at": current.isoformat(),
        "score": score,
        "label": label,
        "tone": tone,
        "greeting": f"{greeting}, {name}",
        "headline": headline,
        "pending": len(tasks),
        "overdue": len(overdue),
        "due_today": len(due_today),
        "next_action": next_action,
        "signals": signals[:3],
        "organize_prompt": "Organiza mi día con mis tareas, proyectos y calendario. Sé breve y dame las tres prioridades más importantes.",
    }
