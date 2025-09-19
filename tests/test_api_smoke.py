import os
import time
import json
import urllib.request
import urllib.error

BASE = os.getenv("API_BASE", "http://localhost:8000")
API_TIMEOUT = float(os.getenv("API_TIMEOUT", "180"))

def http(method: str, path: str, data: dict | None = None, headers: dict | None = None):
    url = f"{BASE}{path}"
    body = None
    req_headers = headers or {}
    if data is not None:
        body = json.dumps(data).encode()
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            return resp.getcode(), json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            payload = e.read().decode()
            parsed = json.loads(payload) if payload else {}
        except Exception:
            parsed = {}
        return e.code, parsed


def wait_health(timeout=20):
    start = time.time()
    while time.time() - start < timeout:
        try:
            code, data = http("GET", "/health")
            if code == 200 and data.get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.5)
    return False


def test_health():
    assert wait_health(), "backend health failed"


def test_clients_and_knowledge_flow():
    # create client (idempotent)
    code, out = http("POST", "/clients/", {"slug": "test", "name": "Test"})
    if code == 409:
        # slug exists; fetch existing
        code, clients = http("GET", "/clients/")
        assert code == 200
        out = next(c for c in clients if c["slug"] == "test")
        code = 200
    assert code == 200
    client_id = out["id"]

    # add note
    code, note = http("POST", f"/knowledge/{client_id}/notes", {"text": "note_for_test_flow_abc"})
    assert code == 200
    note_id = note["id"]

    # reindex (first call may download model; allow longer timeout)
    code, r = http("POST", f"/retrieval/{client_id}/reindex")
    assert code == 200

    # search
    code, results = http("GET", f"/retrieval/{client_id}/search?q=note_for_test_flow_abc&k=3")
    assert code == 200
    assert any("note_for_test_flow_abc" in item["text"] for item in results)

    # cleanup
    code, ok = http("DELETE", f"/knowledge/{client_id}/{note_id}")
    assert code == 200
    assert ok.get("ok") is True
