"""Call one of your Custom Agent Platform agents from Python (standard library only)."""
import json
import urllib.error
import urllib.request

__all__ = ["Agent", "AgentError"]


class AgentError(Exception):
    def __init__(self, status, code, message, retry_after=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after


class Agent:
    def __init__(self, api_key, base_url="http://localhost:8000"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def run(self, message):
        req = urllib.request.Request(
            self.base_url + "/v1/run",
            data=json.dumps({"message": message}).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=200) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as err:
            code, message = "http_error", "HTTP %d" % err.code
            try:
                detail = json.loads(err.read())["detail"]
                code, message = detail["code"], detail["message"]
            except (ValueError, KeyError, TypeError):
                pass
            retry = err.headers.get("Retry-After")
            raise AgentError(err.code, code, message, int(retry) if retry and retry.isdigit() else None) from None
