"""Send the generated price report to Telegram chats listed in id.txt."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096
REQUEST_TIMEOUT = 30


def _message_chunks(text: str, limit: int = MAX_MESSAGE_LENGTH):
    """Split text without exceeding Telegram's message-size limit."""
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit + 1)
        if split_at <= 0:
            split_at = limit
        yield text[:split_at]
        text = text[split_at:].lstrip("\n")
    if text:
        yield text


def send_message(chat_id: str | int, text: str) -> list[dict]:
    """Send text to one Telegram chat and return each API response."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    text = str(text).strip()
    if not text:
        return []

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    responses: list[dict] = []
    for chunk in _message_chunks(text):
        for attempt in range(3):
            try:
                response = requests.post(
                    url,
                    json={"chat_id": str(chat_id), "text": chunk},
                    timeout=REQUEST_TIMEOUT,
                )
                data = response.json()
                if response.ok and data.get("ok"):
                    responses.append(data)
                    break

                retryable = response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt == 2:
                    description = data.get("description", response.text)
                    raise RuntimeError(
                        f"Telegram send failed for chat {chat_id}: {description}"
                    )
                retry_after = data.get("parameters", {}).get("retry_after", 2**attempt)
                time.sleep(float(retry_after))
            except requests.RequestException as exc:
                if attempt == 2:
                    raise RuntimeError(
                        f"Telegram request failed for chat {chat_id}: {exc}"
                    ) from exc
                time.sleep(2**attempt)
    return responses


def _read_chat_ids(path: Path) -> list[str]:
    """Read unique chat IDs, ignoring blank lines and comments."""
    chat_ids: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        chat_id = line.split("#", 1)[0].strip()
        if not chat_id:
            continue
        if not chat_id.lstrip("-").isdigit():
            raise ValueError(f"Invalid Telegram chat ID at {path}:{line_number}")
        if chat_id not in chat_ids:
            chat_ids.append(chat_id)
    return chat_ids


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    report_path = Path(sys.argv[1]) if len(sys.argv) > 1 else base_dir / "price.txt"
    id_path = Path(sys.argv[2]) if len(sys.argv) > 2 else base_dir / "id.txt"
    report = report_path.read_text(encoding="utf-8").strip()
    if not report:
        print("No matching price signals; no Telegram message sent.")
        return 0

    chat_ids = _read_chat_ids(id_path)
    if not chat_ids:
        raise RuntimeError(f"No Telegram chat IDs found in {id_path}")

    failures: list[str] = []
    for chat_id in chat_ids:
        try:
            count = len(send_message(chat_id, report))
            print(f"Sent {count} Telegram message(s) to chat {chat_id}.")
        except Exception as exc:
            failures.append(str(exc))
            print(str(exc), file=sys.stderr)

    if failures:
        print(f"Failed to send to {len(failures)} of {len(chat_ids)} chat(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
