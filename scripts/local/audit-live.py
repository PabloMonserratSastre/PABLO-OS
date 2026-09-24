"""Opt-in live planning audit. Synthetic context only; never executes proposed tools.

One case per invocation so callers can respect the configured provider's free quota.
Credentials stay server-side and are not included in the report.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from run import load_environment, ROOT

os.chdir(ROOT)
load_environment()
sys.path.insert(0, str(ROOT / "backend"))
from pablo.providers import CompatibleProvider

CASES = [
    ("Hola tío, ¿qué tal estás?", []),
    ("Me vendría bien apuntar que tengo que llamar al dentista; ponlo como tarea con prioridad alta.", ["tasks.create"]),
    ("Consulta por favor mi agenda de Google del próximo viernes, solo los eventos de ese día.", ["google_calendar.list"]),
    ("Busca los tres últimos correos recibidos en Gmail; no envíes nada.", ["email.list"]),
    ("Dame tres ideas para organizar una mudanza, sin crear tareas ni ejecutar cambios.", []),
    ("Cambia la tarea Comprar pan para que se llame Comprar fruta.", ["items.update"]),
    ("Hazme una web sencilla para un restaurante ficticio llamado Luna, con un menú y un botón que muestre el teléfono 123. Guárdala en una carpeta nueva.", ["code.scaffold"]),
]
index = int(sys.argv[1])
goal, expected = CASES[index]
now = datetime.now(ZoneInfo("Europe/Madrid"))
context = {"today": now.date().isoformat(), "current_local_datetime": now.isoformat(), "timezone": "Europe/Madrid", "tasks": [{"id": "synthetic-task", "title": "Comprar pan", "priority": "MEDIUM"}], "conversation": []}
provider = CompatibleProvider()
if provider.base != "https://api.groq.com/openai/v1":
    raise SystemExit("Live audit limited to the user's configured Groq provider; no automatic paid fallback.")
result = {"case": index, "goal": goal, "expected": expected, "model": provider.model, "timestamp": now.isoformat(), "executed_tools": False}
try:
    plan, usage = provider.plan(goal, "CHAT", context)
    actual = [step.tool for step in plan.steps]
    result.update(status="PASS" if actual == expected and plan.summary.strip() else "FAIL", actual=actual, plan=plan.model_dump(), tokens=usage.get("total_tokens"))
    if index == 2 and actual == expected:
        start = datetime.fromisoformat(plan.steps[0].arguments["start"])
        if start.weekday() != 4 or start.date() <= now.date():
            result.update(status="FAIL", error="La fecha elegida no es el próximo viernes.")
    if index == 1 and actual == expected and plan.steps[0].arguments.get("priority") != "HIGH":
        result.update(status="FAIL", error="No conserva la prioridad alta solicitada.")
    if index == 3 and actual == expected and plan.steps[0].arguments.get("limit") != 3:
        result.update(status="FAIL", error="No conserva el límite de tres correos.")
    if index == 6 and actual == expected and (plan.steps[0].arguments.get("kind") != "web" or not plan.steps[0].arguments.get("html")):
        result.update(status="FAIL", error="No genera una web personalizada.")
except Exception as error:
    result.update(status="ERROR", error=str(error))
out = ROOT / ".local" / "audit-live.jsonl"
with out.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
print(json.dumps(result, ensure_ascii=True))
