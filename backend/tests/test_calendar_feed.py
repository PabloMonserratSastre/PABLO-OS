from pablo import integrations


URL = "/api/v1/integrations/google/calendar-events?start=2026-09-01T00:00:00Z&end=2026-10-13T00:00:00Z"


def test_calendar_feed_disconnected(client):
    assert client.get(URL).json() == {"events": [], "connected": False, "truncated": False}


def test_calendar_feed_pages_and_dates(client, monkeypatch):
    monkeypatch.setattr(integrations, "credentials", lambda *a: {"access_token": "test"})
    calls = []
    def google(db, service, method, path, **kwargs):
        calls.append(kwargs["params"])
        assert service == "calendar" and method == "GET" and path == "calendars/primary/events"
        if len(calls) == 1:
            return {"items": [{"id": "day", "summary": "Todo el día",
                               "start": {"date": "2026-09-12"}, "end": {"date": "2026-09-13"}}],
                    "nextPageToken": "page2"}
        return {"items": [{"id": "cancelled", "status": "cancelled"},
                          {"id": "timed", "start": {"dateTime": "2026-09-12T10:00:00+02:00"},
                           "end": {"dateTime": "2026-09-12T11:00:00+02:00"}}]}
    monkeypatch.setattr(integrations, "_google", google)
    result = client.get(URL)
    assert result.status_code == 200
    rows = result.json()["events"]
    assert len(rows) == 2
    assert rows[0]["all_day"] and rows[0]["end"] == "2026-09-13T00:00:00"
    assert rows[1]["start"] == "2026-09-12T10:00:00+02:00"
    assert calls[1]["pageToken"] == "page2"


def test_calendar_feed_failure_is_not_empty_success(client, monkeypatch):
    monkeypatch.setattr(integrations, "credentials", lambda *a: {"access_token": "test"})
    def fail(*a, **kw):
        raise ValueError("Reconecta Google y concede permisos para calendar.")
    monkeypatch.setattr(integrations, "_google", fail)
    response = client.get(URL)
    assert response.status_code == 422
    assert "Reconecta" in response.text


def test_calendar_feed_rejects_unbounded_range(client):
    assert client.get(URL.replace("2026-10-13", "2027-10-13")).status_code == 422

