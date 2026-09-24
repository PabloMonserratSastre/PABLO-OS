"""User-facing summaries are derived from recorded tool results, not invented statuses."""

import json


def render_results(steps: list[dict]) -> str:
    sections = []
    for step in steps:
        tool, result = step["tool"], step.get("result")
        if tool == "daily.summary" and isinstance(result, dict):
            sections.append(result["text"])
            continue
        if tool in {"items.create", "items.update", "items.delete", "schedules.update", "schedules.delete"} and isinstance(result, dict):
            verb = "Eliminado" if result.get("deleted") else "Creado" if tool.endswith("create") else "Actualizado"
            sections.append(f"**{verb}: {result.get('title', '')}**\nCambio guardado y verificado.")
            continue
        if tool == "projects.list":
            sections.append("**Tus proyectos**\n\n" + ("\n".join("• " + row["title"] for row in result) if result else "No hay proyectos que coincidan con la consulta."))
        elif tool == "tasks.list":
            lines = ["**Tus tareas pendientes**"]
            if not result:
                lines.append("No hay tareas pendientes en este contexto.")
            for row in result or []:
                priority = {"HIGH": "alta", "MEDIUM": "media", "LOW": "baja"}.get(
                    row.get("priority"), "media"
                )
                lines.append(
                    f"• {row['title']} — prioridad {priority}"
                    + (f" · {row['due']}" if row.get("due") else "")
                )
            sections.append("\n".join(lines))
        elif tool in {"projects.create", "tasks.create", "report.create"} and isinstance(result, dict):
            noun = {
                "projects.create": "Proyecto creado",
                "tasks.create": "Tarea creada",
                "report.create": "Informe guardado",
            }[tool]
            sections.append(f"**{noun}:** {result.get('title', '')}")
        elif tool == "code.scaffold" and isinstance(result, dict):
            sections.append(f"**Proyecto creado: {result.get('name', '')}**\nLo encontrarás en Workspace, en la carpeta **{result.get('path', '')}**.\nAbre index.html junto con styles.css y script.js.\n{result.get('scope', '')}")
        elif tool == "workspace.write" and isinstance(result, dict):
            sections.append(f"**Archivo guardado:** {result.get('path', '')}\nPuedes verlo y descargarlo en Workspace.")
        elif tool == "workspace.list" and isinstance(result, dict):
            sections.append("**Archivos de Workspace**\n" + ("\n".join(f"• {row['path']}" for row in result.get("files", [])) or "Todavía no hay archivos en esta carpeta.") + ("\nHay más archivos; consulta una subcarpeta." if result.get("truncated") else ""))
        elif tool == "calendar.list" and isinstance(result, dict):
            sections.append("**Tu calendario local**\n" + ("\n".join(f"• {row.get('title', 'Sin título')} · {row.get('start', '')}" for row in result.get("events", [])) or "No hay eventos locales en el intervalo consultado.") + "\nEsta consulta no incluye Google Calendar.")
        elif tool == "documents.search":
            sections.append(
                "**Fragmentos encontrados**\n"
                + (
                    "\n\n".join(
                        f"**{row['source']} · fragmento {row['fragment']}**\n{row['text']}" for row in result
                    )
                    if result
                    else "No encontré fragmentos relevantes. Prueba palabras más concretas."
                )
            )
        elif tool == "memory.search":
            sections.append(
                "**Memoria relevante**\n"
                + (
                    "\n".join(f"• {row['title']}: {row.get('description', '')}" for row in result)
                    if result
                    else "No hay recuerdos permitidos que coincidan."
                )
            )
        elif tool == "github.inspect" and isinstance(result, dict):
            sections.append(
                f"**Repositorio consultado: {result.get('repository', '')}**\n{result.get('description') or ''}\nLenguaje: {result.get('language') or 'No indicado'} · rama: {result.get('default_branch', '')}\n{result.get('scope', '')}\n\n**Extracto del README**\n{result.get('readme', '')[:2000]}"
            )
        elif tool == "web.search" and isinstance(result, dict):
            lines = [f"**Fuentes consultadas · {result.get('provider', 'Web')}**"]
            for row in result.get("results", []):
                lines.append(f"**{row.get('title', '')}**\n{row.get('snippet', '')}\n{row.get('url', '')}")
            if not result.get("results"):
                lines.append("No se encontraron resultados para esa consulta.")
            sections.append("\n\n".join(lines))
        elif tool == "google_calendar.list" and isinstance(result, dict):
            from datetime import datetime
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(result.get("timezone", "Europe/Madrid"))
            lines = ["**Tu agenda de Google Calendar**", ""]
            for event in result.get("events", []):
                start = event.get("start") or {}
                if start.get("date"):
                    when = datetime.fromisoformat(start["date"]).strftime("%d/%m/%Y") + " · Todo el día"
                elif start.get("dateTime"):
                    when = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(zone).strftime("%d/%m/%Y · %H:%M")
                else:
                    when = "Hora sin especificar"
                lines.append(f"• **{when}** — {event.get('summary') or 'Sin título'}")
            if not result.get("events"):
                lines.append("No hay eventos en el intervalo consultado.")
            if result.get("next_page_token"):
                lines.append("Hay más eventos disponibles en este intervalo.")
            sections.append("\n".join(lines))
        elif tool == "email.list" and isinstance(result, dict):
            messages = result.get("messages", [])
            lines = ["**Correos consultados en Gmail**"]
            for message in messages:
                lines.append(f"• {message.get('subject') or '(Sin asunto)'} — {message.get('from', '')} · {message.get('date', '')}")
            if not messages:
                lines.append("No hay correos que coincidan con esta búsqueda.")
            if result.get("next_page_token"):
                lines.append("Hay más resultados; esta lista muestra solo la primera página.")
            sections.append("\n".join(lines))
        elif result is not None:
            sections.append(f"**{tool} · resultado registrado**\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)[:30000]}\n```")
    return "\n\n".join(sections)
