#!/usr/bin/env python3
"""Collect today's numbers from every configured platform and append a snapshot.

    python3 collect.py

Design rule: a platform that fails must never take the others down with it. Each
collector is isolated — a bad token on Instagram records an error against
Instagram and leaves YouTube's real number intact. The run only exits non-zero if
*every* configured platform failed, which is the one case that means something is
broken with the setup rather than with one platform.

Platforms with no credentials are simply skipped and show as "not connected" on
the dashboard, so this is safe to run with only YouTube configured.
"""

import importlib
import os
import sys

from store import (
    PLATFORM_LABELS,
    PLATFORMS,
    empty_platform,
    load_history,
    save_history,
    today_utc,
    upsert_snapshot,
)

# A platform is "configured" if its trigger env var is present. Keeps an
# unconfigured platform from reporting a scary auth error every single day.
TRIGGER_VARS = {
    "youtube": "YOUTUBE_API_KEY",
    "instagram": "INSTAGRAM_ACCESS_TOKEN",
    "facebook": "FACEBOOK_PAGE_TOKEN",
    "tiktok": "TIKTOK_CLIENT_KEY",
}


def collect_one(platform):
    if not os.environ.get(TRIGGER_VARS[platform]):
        return empty_platform("not configured")

    try:
        module = importlib.import_module(f"collectors.{platform}")
    except ModuleNotFoundError:
        return empty_platform("collector not implemented yet")

    try:
        followers, views_total, views_28d = module.fetch()
    except Exception as e:  # noqa: BLE001 — one platform must not break the run
        return empty_platform(str(e))

    return {
        "ok": True,
        "followers": followers,
        "views_total": views_total,
        "views_28d": views_28d,
        "error": None,
    }


def main():
    results = {p: collect_one(p) for p in PLATFORMS}

    configured = [p for p in PLATFORMS if os.environ.get(TRIGGER_VARS[p])]
    succeeded = [p for p in configured if results[p]["ok"]]

    for p in PLATFORMS:
        r = results[p]
        label = PLATFORM_LABELS[p]
        if r["ok"]:
            print(f"  {label:<10} followers={r['followers']!s:<10} views={r['views_total'] or r['views_28d']}")
        elif r["error"] == "not configured":
            print(f"  {label:<10} skipped (no credentials)")
        else:
            print(f"  {label:<10} FAILED: {r['error']}", file=sys.stderr)

    if not configured:
        print("\nNo platforms configured. Set at least YOUTUBE_API_KEY.", file=sys.stderr)
        return 1

    history = load_history()
    upsert_snapshot(history, {"date": today_utc(), "platforms": results})
    save_history(history)
    print(f"\nSaved snapshot for {today_utc()} ({len(history['snapshots'])} total).")

    if not succeeded:
        print("Every configured platform failed — check credentials.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
