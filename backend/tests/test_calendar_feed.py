"""Google integration routes are intentionally absent from the focused product."""
import pytest


@pytest.mark.parametrize("path", [
    "/api/v1/integrations/google/calendar-events?start=2026-09-01T00:00:00Z&end=2026-10-13T00:00:00Z",
    "/api/v1/integrations/google/callback?state=old&code=old",
    "/api/v1/integrations/github",
])
def test_integration_routes_retired(client, path):
    assert client.get(path).status_code == 404
