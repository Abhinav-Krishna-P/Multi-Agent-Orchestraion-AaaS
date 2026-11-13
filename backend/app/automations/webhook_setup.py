"""One-time and per-session setup of Composio's webhook address.
    python -m app.automations.webhook_setup create <public_url>   (first time)
    python -m app.automations.webhook_setup update <public_url>   (each new tunnel address)"""
import asyncio
import re
import sys
from pathlib import Path

from app.integrations import composio
from app.tools.http import ToolError

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
PATH = "/webhooks/composio"


def save_to_env(path: Path, values: dict[str, str]) -> None:
    """Sets KEY=value lines, replacing existing ones and leaving every other line as it was."""
    text = path.read_bytes().decode() if path.exists() else ""  # bytes: text mode would rewrite line endings
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    for key, value in values.items():
        line = f"{key}={value}"
        for i, existing in enumerate(lines):
            if existing.startswith(f"{key}="):
                lines[i] = line
                break
        else:
            lines.append(line)
    path.write_bytes((newline.join(lines) + newline).encode())


def _saved_id(path: Path) -> str | None:
    found = re.search(r"^COMPOSIO_WEBHOOK_ID=(.+?)\s*$", path.read_text(encoding="utf-8") if path.exists() else "", re.MULTILINE)
    return found.group(1) if found else None


async def main(argv: list[str], env_path: Path = ENV_PATH) -> int:
    if len(argv) != 2 or argv[0] not in ("create", "update"):
        print("Usage: python -m app.automations.webhook_setup create|update <public_url>")
        return 2
    command, url = argv[0], argv[1].rstrip("/") + PATH
    try:
        if command == "create":
            subscription_id, secret = await composio.create_webhook(url)
            save_to_env(env_path, {"COMPOSIO_WEBHOOK_SECRET": secret, "COMPOSIO_WEBHOOK_ID": subscription_id})
            print("Saved the webhook secret to backend/.env.")
        else:
            subscription_id = _saved_id(env_path)
            if not subscription_id:
                print("No webhook is saved yet. Run create first.")
                return 1
            await composio.update_webhook(subscription_id, url)
            print("Updated the webhook address.")
    except ToolError:
        # http.py folds a 409 into the same error as any refusal, so say both.
        print("Composio did not accept that. If the webhook already exists, run update instead of create.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
