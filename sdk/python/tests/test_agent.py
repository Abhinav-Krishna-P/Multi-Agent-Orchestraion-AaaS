import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentplatform import Agent, AgentError


def serve(status, body, headers=None, ctype="application/json"):
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["method"] = self.command
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


@pytest.fixture
def stop():
    servers = []
    yield servers.append
    for s in servers:
        s.shutdown()
        s.server_close()


def test_run_sends_key_and_message(stop):
    reply = {"id": "1", "agent_id": "a", "reply": "yo", "sources": [], "tools_used": [], "duration_ms": 5}
    srv, seen = serve(200, reply)
    stop(srv)
    out = Agent(api_key="cap_test", base_url=f"http://127.0.0.1:{srv.server_port}").run("hi")
    assert out == reply
    assert seen["method"] == "POST" and seen["path"] == "/v1/run"
    assert seen["auth"] == "Bearer cap_test"
    assert seen["body"] == {"message": "hi"}


def test_errors_raise_agent_error(stop):
    srv, _ = serve(429, {"detail": {"code": "rate_limited", "message": "Slow down"}}, {"Retry-After": "7"})
    stop(srv)
    with pytest.raises(AgentError) as ei:
        Agent(api_key="k", base_url=f"http://127.0.0.1:{srv.server_port}").run("hi")
    e = ei.value
    assert (e.status, e.code, e.message, e.retry_after) == (429, "rate_limited", "Slow down", 7)


def test_non_json_error_still_raises(stop):
    srv, _ = serve(502, b"<html>bad gateway</html>", ctype="text/html")
    stop(srv)
    with pytest.raises(AgentError) as ei:
        Agent(api_key="k", base_url=f"http://127.0.0.1:{srv.server_port}").run("hi")
    assert ei.value.status == 502 and ei.value.code == "http_error" and ei.value.retry_after is None


def test_trailing_slash_in_base_url(stop):
    srv, seen = serve(200, {"reply": "ok"})
    stop(srv)
    Agent(api_key="k", base_url=f"http://127.0.0.1:{srv.server_port}/").run("hi")
    assert seen["path"] == "/v1/run"
