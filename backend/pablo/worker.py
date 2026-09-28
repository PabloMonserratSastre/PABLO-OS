"""Single worker; transactionally checkpoints each tool and its effects together."""

import json
import os
import time

from sqlalchemy import or_, select, update

from .db import DB, Approval, Item, Owner, Run, Runtime, audit, now, uid
from .integrations import approval_context
from .knowledge import search
from .presentation import render_results
from .providers import CompatibleProvider, local_plan
from .scheduling import dispatch_due
from .tools import memory_search, registry, task_list

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "PLANNED", "BLOCKED"}


def finish(db, run, status, text):
    run.status, run.result, run.updated_at = status, text, now()
    db.add(
        Item(
            kind="messages",
            title="PABLO",
            data={
                "conversation_id": run.conversation_id,
                "role": "assistant",
                "content": text,
                "run_id": run.id,
            },
        )
    )
    audit(db, "execution.finished", status, run.id)


def tick(run_id: str):
    with DB() as db:
        run = db.get(Run, run_id)
        if not run or run.status in TERMINAL or run.status == "WAITING_APPROVAL":
            return
        if run.status == "QUEUED":
            owner = db.get(Owner, 1)
            audit(db, "planning.started", run_id=run.id)
            db.commit()
            context = {"project": None, "memory": memory_search(db, {"query": run.goal}, run.project_id)}
            context["current_time_utc"] = now()
            context["timezone"] = owner.settings.get("timezone", "Europe/Madrid")
            from datetime import datetime
            from zoneinfo import ZoneInfo
            local_now = datetime.now(ZoneInfo(context["timezone"]))
            context["current_local_datetime"] = local_now.isoformat()
            context["today"] = local_now.date().isoformat()
            tasks = task_list(db, {}, run.project_id)
            context["pending_tasks"] = [{key: task.get(key) for key in ("title", "priority", "due", "status")}
                                        for task in tasks[:15]]
            context["pending_tasks_note"] = "Hasta 15 tareas, ordenadas por prioridad y fecha; puede haber más."
            if run.project_id:
                project = db.get(Item, run.project_id)
                context["project"] = {"title": project.title, **project.data} if project else None
            history = db.scalars(
                select(Item)
                .where(
                    Item.kind == "messages", Item.data["conversation_id"].as_string() == run.conversation_id,
                    Item.created_at < run.created_at,
                )
                .order_by(Item.created_at.desc())
                .limit(12)
            ).all()
            context["conversation"] = [
                {"role": r.data.get("role", "user"), "content": r.data.get("content", "")[:2400]}
                for r in reversed(history)
                if r.data.get("conversation_id") == run.conversation_id and r.data.get("run_id") != run.id
            ][-12:]
            from .commands import explicit_plan
            exact = explicit_plan(run.goal, run.mode, context["timezone"])
            if exact is None and run.mode in {"CHAT", "ASK", "RESEARCH"}:
                from .pdf_tables import timetable_answer
                from .schemas import Plan
                answer = timetable_answer(db, run.goal, context['conversation'], run.project_id)
                if answer:
                    exact = Plan(summary=answer, steps=[])
            # Simple commands do not need document retrieval or an embeddings call.
            context["documents"] = [] if exact is not None else search(db, run.goal, run.project_id)
            provider = CompatibleProvider()
            if not exact and provider.config.get("credential_error"):
                raise ValueError(provider.config["credential_error"])
            if exact:
                plan, usage, source = exact, {"synthesis": False}, "LOCAL_COMMAND"
            elif provider.key and provider.model and not owner.settings.get("demo", False):
                daily = db.scalars(select(Run).where(Run.created_at >= now()[:10])).all()
                if sum(r.usage.get("total_tokens", 0) for r in daily) >= int(
                    os.getenv("DAILY_TOKEN_LIMIT", "50000")
                ):
                    raise ValueError("Límite diario de tokens alcanzado.")
                if run.mode == "ASK" and provider.is_local:
                    answer, usage = provider.quick_answer(run.goal, context)
                    db.refresh(run)
                    if run.status in TERMINAL:
                        return
                    run.usage = usage | {"provider": "AI", "retries": run.usage.get("retries", 0)}
                    finish(db, run, "COMPLETED", answer)
                    db.commit()
                    return
                plan, usage = provider.plan(run.goal, run.mode, context)
                source = "LOCAL_COMMAND" if usage.get("deterministic") else "AI"
            else:
                if run.mode == "CHAT":
                    raise ValueError("Configura un proveedor de IA y desactiva el modo demo en Ajustes para interpretar esta petición.")
                plan, usage = local_plan(run.goal, run.mode, run.project_id), {}
                source = "LOCAL_TEMPLATE"
            # A cancellation may have arrived while the provider was running.
            db.refresh(run)
            if run.status == "CANCELLED":
                return
            steps = [s.model_dump() | {"status": "PENDING", "result": None} for s in plan.steps]
            for i, step in enumerate(steps):
                if any(d < 0 or d >= i for d in step["depends_on"]):
                    raise ValueError("Dependencias del plan inválidas o cíclicas.")
                registry.get(step["tool"])
            run.plan, run.usage, run.result = (
                steps,
                usage | {"provider": source, "retries": run.usage.get("retries", 0)},
                plan.summary,
            )
            if run.mode == "PLAN":
                finish(
                    db,
                    run,
                    "PLANNED",
                    plan.summary
                    + "\n\n"
                    + "\n".join(
                        f"{i + 1}. {s['tool']}: {json.dumps(s['arguments'], ensure_ascii=False)}"
                        for i, s in enumerate(steps)
                    ),
                )
            else:
                run.status = "RUNNING"
            audit(db, "plan.created", run_id=run.id, step_count=len(steps), provider=source)
            db.commit()
            return
        owner = db.get(Owner, 1)
        steps = json.loads(json.dumps(run.plan))
        pending = next(((i, step) for i, step in enumerate(steps) if step["status"] != "DONE"), None)
        if pending is None:
            outputs = render_results(steps)
            # Connected services can contain private mail, calendar and files.
            # Present those results locally instead of forwarding them to an AI
            # provider for a second pass. The execution details retain the raw
            # checkpoint for diagnostics; the conversation gets a clean answer.
            final = outputs or run.result
            finish(db, run, "COMPLETED", final)
            db.commit()
            return
        index, step = pending
        if any(steps[d]["status"] != "DONE" for d in step["depends_on"]):
            raise ValueError("Dependencia pendiente.")
        tool = registry.get(step["tool"])
        if tool.id in {"schedules.update", "schedules.delete"} and "expected" not in step["arguments"]:
            from .schedule_tools import resolve, snapshot
            target = resolve(db, step["arguments"], run.project_id)
            step["arguments"] = step["arguments"] | {"id": target.id, "title": target.title, "expected": snapshot(target)}
            run.plan = steps
        if tool.id in {"items.update", "items.delete"} and "version" not in step["arguments"]:
            from .item_tools import resolve
            target = resolve(db, step["arguments"], run.project_id)
            step["arguments"] = step["arguments"] | {"id": target.id, "title": target.title, "version": target.version}
            run.plan = steps
        if run.mode not in {"DO", "CHAT"} and tool.risk != "SAFE":
            finish(
                db,
                run,
                "BLOCKED",
                "El plan contiene cambios. Selecciona Hacer para solicitar su ejecución; no se han aplicado estos cambios.",
            )
            db.commit()
            return
        needs_approval = (
            tool.risk in {"HIGH", "CRITICAL"}
            or owner.settings.get("autonomy", "ASSISTED") == "MANUAL"
            or (tool.risk == "MODERATE" and owner.settings.get("autonomy", "ASSISTED") != "AUTONOMOUS")
        )
        approval = db.scalar(
            select(Approval).where(Approval.run_id == run.id, Approval.tool == f"{index}:{tool.id}")
        )
        connection = approval_context(db, tool.id)
        reviewed_payload = step["arguments"] | ({"_connection": connection} if connection else {})
        if needs_approval and not approval:
            db.add(Approval(run_id=run.id, tool=f"{index}:{tool.id}", payload=reviewed_payload))
            run.status = "WAITING_APPROVAL"
            audit(db, "approval.requested", "WAITING", run.id, tool=tool.id)
            db.commit()
            return
        if approval and approval.status != "APPROVED":
            run.status = "WAITING_APPROVAL"
            db.commit()
            return
        if approval and approval.payload != reviewed_payload:
            raise ValueError("Los parámetros no coinciden con la aprobación.")
        if step["status"] == "EXECUTING":
            finish(db, run, "BLOCKED", "La acción se interrumpió y su resultado es incierto. Comprueba el destino antes de solicitar una nueva ejecución; no se repetirá automáticamente.")
            db.commit()
            return
        started = time.monotonic()
        # Short DB transaction binds tool result, effects, audit and checkpoint.
        # Files/processes/remote writes cannot share the SQL transaction. Persist
        # intent first; interrupted effects are never replayed automatically.
        arguments = dict(step["arguments"])
        if tool.id == "tasks.create":
            arguments["dependencies"] = [
                steps[d]["result"]["id"] for d in step["depends_on"] if steps[d]["tool"] == "tasks.create"
            ]
        external_effect = tool.id in {
            "workspace.write", "code.scaffold", "game.scaffold", "code.run", "git.branch", "files.create",
            "email.send", "google_calendar.create", "github.branch", "github.write",
            "n8n.trigger", "notion.create",
        }
        if external_effect:
            step["status"] = "EXECUTING"
            run.plan = steps
            audit(db, "tool.started", run_id=run.id, tool=tool.id)
            db.commit()
        if tool.id in {"google_calendar.create", "n8n.trigger"}:
            arguments["_idempotency_key"] = f"{run.id}:{index}"
        db.info["executing_run_id"] = run.id
        result = tool.execute(db, arguments, run.project_id)
        if tool.id in {"workspace.write", "code.scaffold", "game.scaffold", "code.run", "git.branch", "files.create"}:
            from .cloud_workspace import checkpoint
            checkpoint(db)
        # Cancellation while a long-running tool executes must not be lost.
        db.refresh(run)
        cancelled = run.status == "CANCELLED"
        if isinstance(result, dict) and result.get("verified") is False:
            step["result"] = result
            run.plan = steps
            if approval:
                approval.status = "EXECUTED"
            if not cancelled:
                finish(db, run, "FAILED", "La herramienta no superó la verificación. Revisa el código de salida y su resultado.\n\n" + render_results([step]))
            db.commit()
            return
        if tool.id == "projects.create" and not run.project_id:
            run.project_id = result["id"]
            conversation = db.get(Item, run.conversation_id)
            if conversation and not conversation.data.get("project_id"):
                conversation.data = conversation.data | {"project_id": result["id"]}

        step["status"], step["result"] = "DONE", result
        run.plan, run.updated_at = steps, now()
        if approval:
            approval.status = "EXECUTED"
        audit(
            db,
            "tool.executed",
            run_id=run.id,
            tool=tool.id,
            agent=tool.agent,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        db.commit()
        if cancelled:
            return


def claim(run_id: str) -> str | None:
    token = uid()
    with DB() as db:
        claimed = db.execute(
            update(Run)
            .where(
                Run.id == run_id,
                Run.status.in_(["QUEUED", "RUNNING"]),
                or_(Run.lease_until.is_(None), Run.lease_until < time.time()),
            )
            .values(lease_token=token, lease_until=time.time() + 180)
        )
        db.commit()
        return token if claimed.rowcount else None


def process(run_id):
    token = claim(run_id)
    if not token:
        return
    try:
        tick(run_id)
    except Exception as exc:
        with DB() as db:
            run = db.get(Run, run_id)
            if run and run.status not in TERMINAL and run.lease_token == token:
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else str(exc.detail) if hasattr(exc, "detail")
                    else "Error interno de ejecución. Revisa la configuración y reintenta."
                )
                completed = [step for step in run.plan if step.get("status") == "DONE"]
                partial = "\n\n**Resultados obtenidos antes del error**\n\n" + render_results(completed) if completed else ""
                finish(db, run, "FAILED", message[:500] + partial)
                db.commit()
    finally:
        with DB() as db:
            db.execute(
                update(Run)
                .where(Run.id == run_id, Run.lease_token == token)
                .values(lease_token=None, lease_until=None)
            )
            db.commit()


def main():
    cloud_lock = None
    if os.getenv("PABLO_CLOUD") == "true":
        from sqlalchemy import text
        from .db import engine
        from .cloud_workspace import restore
        # Rolling deployments can overlap: only one worker may write files or run schedules.
        cloud_lock = engine.connect()
        while not cloud_lock.scalar(text("SELECT pg_try_advisory_lock(73482191)")):
            cloud_lock.commit()
            time.sleep(2)
        cloud_lock.commit()
        with DB() as db:
            restore(db)
    print("PABLO worker listo. Un único worker por instalación.", flush=True)
    last_cleanup = 0
    while True:
        if cloud_lock is not None:
            # Fail rather than continue processing after the advisory-lock connection is lost.
            cloud_lock.exec_driver_sql("SELECT 1")
            cloud_lock.commit()
        if time.monotonic() - last_cleanup > 3600:
            from .capabilities import apply_retention

            apply_retention()
            last_cleanup = time.monotonic()
        dispatch_due()
        with DB() as db:
            db.merge(Runtime(id="worker", updated_at=now()))
            db.commit()
        with DB() as db:
            ids = list(
                db.scalars(
                    select(Run.id)
                    .where(Run.status.in_(["QUEUED", "RUNNING"]))
                    .order_by(Run.created_at)
                    .limit(10)
                )
            )
        for run_id in ids:
            process(run_id)
        time.sleep(0.3 if ids else 1)


if __name__ == "__main__":
    main()
