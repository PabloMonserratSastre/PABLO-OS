from datetime import datetime
from pablo.daily_digest import digest, GOAL
from pablo.db import DB
from pablo.commands import explicit_plan


def test_daily_digest_short_verified_output(client, monkeypatch):
    from pablo import integrations
    monkeypatch.setattr(integrations, "email_list", lambda *a: {"messages": [
        {"from": 'Empresa <private@example.com>', "subject": '  Invitación\n a entrevista  '}]})
    def google(db, service, method, path, **kwargs):
        assert service == "calendar" and path == "calendars/primary/events"
        params = kwargs["params"]
        start, end = datetime.fromisoformat(params["timeMin"]), datetime.fromisoformat(params["timeMax"])
        assert start.hour == end.hour == 0
        assert (end.date() - start.date()).days == 1
        assert params["singleEvents"] == "true"
        return {"items": [{"summary": "Cumpleaños", "start": {"date": start.date().isoformat()}}]}
    monkeypatch.setattr(integrations, "_google", google)
    with DB() as db:
        text = digest(db, {}, None)["text"]
    assert "Hola Pablo test" in text
    assert "Empresa" in text and "Invitación a entrevista" in text
    assert "private@example.com" not in text
    assert "Todo el día" in text and "Cumpleaños" in text
    assert "```" not in text
    assert explicit_plan(GOAL, "DO").steps[0].tool == "daily.summary"


def test_daily_digest_does_not_hide_connection_failure(client, monkeypatch):
    import pytest
    from pablo import integrations
    def fail(*args):
        raise ValueError("Conecta Google")
    monkeypatch.setattr(integrations, "email_list", fail)
    with DB() as db, pytest.raises(ValueError, match="Conecta"):
        digest(db, {}, None)
