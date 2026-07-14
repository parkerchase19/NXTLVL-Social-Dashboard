"""Snapshot storage.

One snapshot per collection run, appended to data/history.json. Re-running on a
date that already has a snapshot replaces it, so a backfill or a retry after a
partial failure doesn't create duplicates.

Normalized snapshot shape:

    {
      "date": "2026-07-13",              # UTC date of collection
      "platforms": {
        "youtube": {
          "ok": true,
          "followers": 1420,             # subscribers / followers / page likes
          "views_total": 288134,         # lifetime cumulative, if the platform has it
          "views_28d": null,             # trailing-28-day, if the platform has it
          "error": null
        },
        ...
      }
    }

followers is the only field every platform reports the same way, which is why the
dashboard leads with it. views_total and views_28d are deliberately separate
fields: they are NOT interchangeable and must never be summed together.
"""

import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(HERE, "data", "history.json")

PLATFORMS = ("instagram", "youtube", "tiktok", "facebook")

PLATFORM_LABELS = {
    "instagram": "Instagram",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "facebook": "Facebook",
}

# What "followers" means on each platform, and what kind of view count it reports.
# Surfaced in the dashboard so the numbers are never silently misread.
PLATFORM_NOTES = {
    "instagram": {
        "followers_term": "Followers",
        "views_term": "Views (last 28 days)",
        "views_field": "views_28d",
    },
    "youtube": {
        "followers_term": "Subscribers",
        "views_term": "Views (all time)",
        "views_field": "views_total",
    },
    "tiktok": {
        "followers_term": "Followers",
        "views_term": "Video views (all time)",
        "views_field": "views_total",
    },
    "facebook": {
        "followers_term": "Page followers",
        "views_term": "Page views (last 28 days)",
        "views_field": "views_28d",
    },
}


def empty_platform(error=None):
    return {
        "ok": error is None,
        "followers": None,
        "views_total": None,
        "views_28d": None,
        "error": error,
    }


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return {"snapshots": []}
    with open(HISTORY_PATH) as f:
        return json.load(f)


def save_history(history):
    history["snapshots"].sort(key=lambda s: s["date"])
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2, sort_keys=True)
        f.write("\n")


def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def upsert_snapshot(history, snapshot):
    """Replace any existing snapshot for the same date, else append."""
    for i, existing in enumerate(history["snapshots"]):
        if existing["date"] == snapshot["date"]:
            history["snapshots"][i] = snapshot
            return history
    history["snapshots"].append(snapshot)
    return history
