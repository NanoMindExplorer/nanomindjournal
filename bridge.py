"""Telegram channel -> Discord bridge (realtime).

Runtime modes:
  --loop <minutes>   Long-lived loop: Telegram getUpdates LONG-POLL (50 s),
                     so each channel_post is relayed the moment it arrives
                     (latency ~1 s). Runs ~5.5 h per Actions job with a cron
                     restart every 5 h.
  (default / --once) Single pass: deliver everything pending, exit.

Delivery discipline: a Telegram update's offset is only confirmed to
Telegram AFTER its Discord message was actually accepted (HTTP 200/204).
A failed delivery leaves the update unconfirmed, so Telegram re-delivers
it and the next poll retries. Nothing is silently lost.

Env: TG_TOKEN (bot token), DC_WEBHOOK (Discord channel webhook).
"""
import os, sys, time, requests

TG = os.environ["TG_TOKEN"]
DC = os.environ["DC_WEBHOOK"]
API_GET = f"https://api.telegram.org/bot{TG}/getUpdates"

OFFSET = 0          # 0 = Telegram returns everything still pending
POSTED = 0


def send(text):
    """Post to Discord; True only when Discord accepted it."""
    for attempt in range(3):
        try:
            r = requests.post(DC, json={"content": text[:2000]}, timeout=30)
        except Exception as e:
            print(f"Discord delivery failed: {e}", file=sys.stderr)
            time.sleep(3)
            continue
        if r.status_code in (200, 204):
            POSTED += 1
            return True
        if r.status_code == 429:
            wait = r.json().get("retry_after", 3) + 1
            time.sleep(wait)
            continue
        if 500 <= r.status_code < 600:
            time.sleep(3)
            continue
        print(f"Discord delivery failed: HTTP {r.status_code}", file=sys.stderr)
        return False
    return False


def poll(wait, offset):
    """One getUpdates call. Long-polls `wait` s while `offset` <= last
    processed update id; returns (updates, failed_delivery)."""
    global OFFSET
    params = {"timeout": wait,
              "allowed_updates": '["channel_post"]'}
    if OFFSET:
        params["offset"] = OFFSET
    r = requests.get(API_GET, params=params, timeout=(10, wait + 15))
    updates = r.json().get("result", []) if isinstance(r.json(), dict) else []
    failed = False
    for u in updates:
        p = u.get("channel_post") or {}
        uid = u.get("update_id")
        text = p.get("text") or p.get("caption")
        if text and not send(text):
            # stop processing this batch on first failure: everything
            # after it (and this one) stays unconfirmed -> retried next poll
            failed = True
            break
        OFFSET = uid + 1
    return failed


def main():
    if not TG or not DC:
        print("TG_TOKEN / DC_WEBHOOK not set", file=sys.stderr)
        return 2

    if "--loop" in sys.argv:
        i = sys.argv.index("--loop")
        minutes = float(sys.argv[i + 1]) if len(sys.argv) > i + 1 \
            and sys.argv[i + 1].replace(".", "", 1).isdigit() else 330.0
        deadline = time.time() + minutes * 60
        cycle = 0
        # drain any pending backlog first (short wait), then go realtime
        poll(5, OFFSET)
        print(f"backlog drained: {POSTED} message(s) relayed", flush=True)
        while time.time() < deadline:
            cycle += 1
            start = time.time()
            failed = poll(50, OFFSET)
            if failed:
                print("delivery failed — update stays unconfirmed, retrying", file=sys.stderr)
                time.sleep(10)
            print(f"cycle {cycle}: {POSTED} relayed so far, "
                  f"{time.time() - start:.0f}s this cycle", flush=True)
        print(f"loop done after {cycle} long-poll cycle(s), {POSTED} messages total")
        return 0

    # single-pass mode (also the --backfill path: delivers everything pending)
    poll(5, OFFSET)
    print(f"done: {POSTED} message(s) relayed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
