"""Logs in to a website (optional), checks a page for new items (courses) and sends a push notification via ntfy.sh.

Environment variables:
  PAGE_URL     page to watch (required)
  LOGIN_URL    login page address (set it if the site needs a login)
  SITE_USER    your username/email on the site
  SITE_PASS    your password on the site
  USER_FIELD   optional: name of the username input (auto-detected if empty)
  PASS_FIELD   optional: name of the password input (auto-detected if empty)
  SELECTOR     optional CSS selector for the items to track (default: all links on the page)
  NTFY_TOPIC   your private ntfy topic name (required unless DRY_RUN=1)
  VERIFY_SSL   set to 0 only if the site has a broken certificate
  DRY_RUN      "1" = print instead of sending the notification
"""
import hashlib, json, os, sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

STATE = Path("state.json")
URL = os.environ.get("PAGE_URL", "").strip()
LOGIN_URL = os.environ.get("LOGIN_URL", "").strip()
USER = os.environ.get("SITE_USER", "")
PASSWORD = os.environ.get("SITE_PASS", "")
USER_FIELD = os.environ.get("USER_FIELD", "").strip()
PASS_FIELD = os.environ.get("PASS_FIELD", "").strip()
SELECTOR = os.environ.get("SELECTOR", "").strip()
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
VERIFY = os.environ.get("VERIFY_SSL", "1") != "0"
DRY = os.environ.get("DRY_RUN") == "1"

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def has_password_form(soup):
    return soup.find("input", {"type": "password"}) is not None


def login():
    r = session.get(LOGIN_URL, timeout=30, verify=VERIFY)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    form = next((f for f in soup.find_all("form") if has_password_form(f)), None)
    if form is None:
        sys.exit("Login form not found on LOGIN_URL (the page may build its form with JavaScript).")

    payload = {}
    for inp in form.find_all(["input", "select", "textarea"]):
        name = inp.get("name")
        if name and inp.get("type") not in ("submit", "button", "checkbox", "radio", "file"):
            payload[name] = inp.get("value", "")  # keeps hidden fields such as CSRF tokens

    pass_name = PASS_FIELD or form.find("input", {"type": "password"}).get("name")
    user_name = USER_FIELD
    if not user_name:
        cand = form.find("input", {"type": lambda t: t in ("text", "email", "tel", None)})
        user_name = cand.get("name") if cand else None
    if not user_name or not pass_name:
        sys.exit("Could not detect login field names. Set USER_FIELD and PASS_FIELD secrets.")
    payload[user_name], payload[pass_name] = USER, PASSWORD

    action = urljoin(r.url, form.get("action") or r.url)
    resp = session.post(action, data=payload, timeout=30, verify=VERIFY, allow_redirects=True)
    resp.raise_for_status()
    print(f"Login request sent (status {resp.status_code}).")


def fetch_items():
    if LOGIN_URL:
        login()
    r = session.get(URL, timeout=30, verify=VERIFY)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    if has_password_form(soup):
        sys.exit("Still on a login page - login failed (wrong username/password, captcha, or extra verification).")
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
    if LOGIN_URL and not (USER and PASSWORD):
        sys.exit("LOGIN_URL is set but SITE_USER / SITE_PASS are missing.")
    items = fetch_items()
    if not items:
        sys.exit("No items found - check PAGE_URL / SELECTOR (page may load its content with JavaScript).")

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
        old.update(new)
        STATE.write_text(json.dumps(old, ensure_ascii=False, indent=1))
    else:
        print("Nothing new.")


if __name__ == "__main__":
    main()
