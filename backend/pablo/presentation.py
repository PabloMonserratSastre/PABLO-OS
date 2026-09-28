"""User-facing summaries are derived from recorded tool results, not invented statuses."""

import re


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
            readme = re.sub(r"<[^>]+>", " ", result.get("readme", ""))
            readme = re.sub(r"!\[[^]]*\]\([^)]*\)", "", readme)
            readme = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", readme)
            readme = re.sub(r"[#*_`>|]+", " ", readme)
            readme = re.sub(r"\s+", " ", readme).strip()
            sections.append(
                f"**{result.get('repository', 'Repositorio')}**\n"
                f"{result.get('description') or 'Sin descripción.'}\n\n"
                f"• Lenguaje principal: {result.get('language') or 'No indicado'}\n"
                f"• Rama principal: {result.get('default_branch', 'No indicada')}\n"
                f"• Incidencias abiertas: {result.get('open_issues', 0)}\n"
                f"• Enlace: {result.get('url', '')}"
                + (f"\n\n**Qué cuenta su README**\n{readme[:900]}" if readme else "")
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
            timed = []
            for event in result.get("events", []):
                start = event.get("start") or {}
                if start.get("date"):
                    when = datetime.fromisoformat(start["date"]).strftime("%d/%m/%Y") + " · Todo el día"
                elif start.get("dateTime"):
                    begin = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(zone)
                    finish_value = (event.get("end") or {}).get("dateTime")
                    finish = datetime.fromisoformat(finish_value.replace("Z", "+00:00")).astimezone(zone) if finish_value else begin
                    timed.append((begin, finish, event.get("summary") or "Sin título"))
                    when = begin.strftime("%d/%m/%Y · %H:%M")
                    if finish > begin:
                        when += "–" + finish.strftime("%H:%M")
                else:
                    when = "Hora sin especificar"
                lines.append(f"• **{when}** — {event.get('summary') or 'Sin título'}")
            if not result.get("events"):
                lines.append("No hay eventos en el intervalo consultado.")
            if result.get("next_page_token"):
                lines.append("Hay más eventos disponibles en este intervalo.")
            conflicts = []
            gaps = []
            for previous, current in zip(sorted(timed), sorted(timed)[1:]):
                if current[0] < previous[1]:
                    conflicts.append(f"{previous[2]} y {current[2]}")
                elif current[0].date() == previous[1].date() and current[0] > previous[1]:
                    minutes = int((current[0] - previous[1]).total_seconds() // 60)
                    gaps.append(f"{previous[1].strftime('%H:%M')}–{current[0].strftime('%H:%M')} ({minutes // 60} h {minutes % 60:02d} min)")
            if conflicts:
                lines.extend(["", "**Solapamientos**", *[f"• {item}" for item in conflicts]])
            elif len(timed) > 1:
                lines.extend(["", "No hay solapamientos entre estos eventos."])
            if gaps:
                lines.extend(["", "**Huecos entre eventos**", *[f"• {item}" for item in gaps]])
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
        elif tool == "email.read" and isinstance(result, dict):
            headers = result.get("headers", {})
            sections.append(
                "**Correo consultado**\n"
                f"• Asunto: {headers.get('subject') or '(Sin asunto)'}\n"
                f"• De: {headers.get('from', '')}\n"
                f"• Fecha: {headers.get('date', '')}\n\n"
                f"{(result.get('text') or result.get('snippet') or '')[:3000]}"
            )
        elif tool == "drive.list" and isinstance(result, dict):
            files = result.get("files", [])
            lines = ["**Archivos encontrados en Google Drive**"]
            lines.extend(f"• **{row.get('name', 'Sin nombre')}** · {row.get('modifiedTime', 'fecha desconocida')}" for row in files)
            if not files:
                lines.append("No encontré archivos que coincidan con la búsqueda.")
            sections.append("\n".join(lines))
        elif tool == "drive.read" and isinstance(result, dict):
            sections.append(f"**{result.get('name', 'Documento de Drive')}**\n\n{(result.get('text') or result.get('detail') or 'No hay texto disponible.')[:5000]}")
        elif tool == "notion.search" and isinstance(result, dict):
            pages = result.get("pages", [])
            sections.append("**Páginas encontradas en Notion**\n" + ("\n".join(f"• **{row.get('title') or 'Sin título'}** — {row.get('url', '')}" for row in pages) if pages else "No encontré páginas que coincidan."))
        elif tool == "notion.read" and isinstance(result, dict):
            text = "\n".join(row.get("text", "") for row in result.get("blocks", []) if row.get("text"))
            sections.append("**Contenido de Notion**\n\n" + (text[:5000] or "La página no contiene texto en sus bloques principales."))
        elif tool == "github.tree" and isinstance(result, dict):
            rows = result.get("files") or result.get("tree") or []
            sections.append("**Estructura del repositorio**\n" + ("\n".join(f"• {row.get('path', '')}" for row in rows[:80]) if rows else "No se encontraron archivos."))
        elif tool == "github.read" and isinstance(result, dict):
            sections.append(f"**{result.get('path', 'Archivo de GitHub')}**\n\n{(result.get('content') or result.get('text') or '')[:5000]}")
        elif result is not None:
            sections.append(f"**Resultado de {tool}**\nLa operación terminó correctamente. Puedes consultar sus detalles técnicos en Actividad.")
    return "\n\n".join(sections)
