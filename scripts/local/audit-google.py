"""Read-only connectivity check. Reports counts only; never logs personal content."""
import json
import os
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from run import ROOT, load_environment

os.chdir(ROOT)
load_environment()
sys.path.insert(0, str(ROOT / "backend"))
from pablo.db import DB, Owner
from pablo.integrations import google_calendar_list, email_list

results = []
with DB() as db:
    owner = db.get(Owner, 1)
    zone = ZoneInfo((owner.settings or {}).get("timezone", "Europe/Madrid"))
    today = datetime.now(zone).date()
    for tool, args, key in [(google_calendar_list, {"start": datetime.combine(today, time.min, zone).isoformat(), "end": datetime.combine(today + timedelta(days=1), time.min, zone).isoformat(), "limit": 10}, "events"), (email_list, {"limit": 1}, "messages")]:
        try:
            data = tool(db, args, None)
            db.commit()  # Preserve OAuth refresh if Google rotated the token.
            results.append({"service": key, "status": "PASS", "count": len(data[key])})
        except Exception as error:
            db.rollback()
            results.append({"service": key, "status": "ERROR", "error": str(error)})
report = {"timestamp": datetime.now(zone).isoformat(), "read_only": True, "results": results}
(ROOT / ".local" / "audit-google.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=True))
