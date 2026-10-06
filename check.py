"""Checks a web page for new items (courses) and sends a push notification via ntfy.sh.

Config via environment variables:
  PAGE_URL     page to watch (required)
  SELECTOR     optional CSS selector for the items to track (e.g. "table tr", ".course a").
               If empty, every link on the page is tracked.
  NTFY_TOPIC   your private ntfy topic name (required unless DRY_RUN=1)
  DRY_RUN      "1" = print instead of sending
"""
import hashlib, json, os, sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STATE = Path("state.json")
URL = os.environ.get("PAGE_URL", "").strip()
SELECTOR = os.environ.get("SELECTOR", "").strip()
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
DRY = os.environ.get("DRY_RUN") == "1"


def fetch_items():
    r = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0 (course-notifier)"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    nodes = soup.select(SELECTOR) if SELECTOR else soup.find_all("a", href=True)
    items = {}
    for n in nodes:
        text = " ".join(n.get_text(" ", strip=True).split())
        if not text:
            continue
        href = n.get("href", "") if n.name == "a" else ""
        key = hashlib.sha1(f"{text}|{href}".encode()).hexdigest()
        items[key] = text
    return items


def notify(title, message):
    if DRY:
        print(f"[DRY RUN] {title}: {message}")
        return
    resp = requests.post(
        f"https://ntfy.sh/{TOPIC}",
        data=message.encode("utf-8"),
        headers={"Title": title.encode("utf-8"), "Priority": "high"},
        timeout=30,
    )
    resp.raise_for_status()


def main():
    if not URL or (not TOPIC and not DRY):
        sys.exit("Set PAGE_URL and NTFY_TOPIC (or DRY_RUN=1).")
    items = fetch_items()
    if not items:
        sys.exit("No items found - check PAGE_URL / SELECTOR (page may need login or load via JavaScript).")

    if not STATE.exists():
        STATE.write_text(json.dumps(items, ensure_ascii=False, indent=1))
        print(f"First run: saved {len(items)} existing items as baseline, no notification.")
        return

    old = json.loads(STATE.read_text())
    new = {k: v for k, v in items.items() if k not in old}
    if new:
        lines = list(new.values())
        notify(f"{len(lines)} new on uni site", "\n".join(lines[:10]))
        print(f"Notified about {len(lines)} new items.")
        old.update(new)  # keep history so removed-then-readded items don't re-alert
        STATE.write_text(json.dumps(old, ensure_ascii=False, indent=1))
    else:
        print("Nothing new.")


if __name__ == "__main__":
    main()
