from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pablo.pulse import build_pulse


def task(title, due="", priority="MEDIUM", status="TODO"):
    return {"kind": "tasks", "title": title, "due": due, "priority": priority, "status": status}


def test_pulse_prioritizes_overdue_work():
    zone = ZoneInfo("Europe/Madrid")
    yesterday = (datetime.now(zone) - timedelta(days=1)).date().isoformat()
    pulse = build_pulse([task("Entregar proyecto", yesterday, "HIGH")], [], 0, "Europe/Madrid", "Pablo")
    assert pulse["overdue"] == 1
    assert pulse["next_action"]["title"] == "Entregar proyecto"
    assert pulse["signals"][0]["kind"] == "overdue"
    assert pulse["score"] < 100


def test_pulse_is_useful_with_an_empty_space_and_invalid_timezone():
    pulse = build_pulse([], [], 0, "Invalid/Timezone", "Pablo")
    assert pulse["score"] == 100
    assert pulse["signals"][0]["kind"] == "clear"
    assert pulse["next_action"]["prompt"]


def test_state_includes_pulse(client):
    state = client.get("/api/v1/state").json()
    assert state["pulse"]["label"] == "En calma"
    assert state["pulse"]["pending"] == 0
