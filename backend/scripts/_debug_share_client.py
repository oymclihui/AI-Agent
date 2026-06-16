import traceback
import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
s = uuid.uuid4().hex[:8]

try:
    r = client.post("/api/v1/auth/register", json={
        "employee_no": f"a_{s}", "password": "SmokeTest123!", "display_name": "A"
    })
    print("reg", r.status_code)
    ta = r.json()["access_token"]
    ha = {"Authorization": f"Bearer {ta}"}
    r = client.post("/api/v1/agents/", headers=ha, json={"name": "T", "role": "R", "goal": "G"})
    aid = r.json()["id"]
    r = client.post("/api/v1/auth/register", json={
        "employee_no": f"b_{s}", "password": "SmokeTest123!", "display_name": "B"
    })
    tb = r.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tb}"})
    bid = me.json()["id"]
    r = client.put(
        f"/api/v1/agents/{aid}/sharing",
        headers=ha,
        json={
            "visibility": "shared",
            "grants": [{"grantee_type": "user", "grantee_id": bid, "permission": "use"}],
        },
    )
    print("share", r.status_code, r.text[:2000])
except Exception:
    traceback.print_exc()
