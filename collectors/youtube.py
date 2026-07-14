"""YouTube collector — YouTube Data API v3, `channels.list`.

The easy one: a plain API key, no OAuth, no app review. Costs 1 quota unit per
call against a 10,000/day allowance, so a daily run uses 0.01% of the budget.

    YOUTUBE_API_KEY    required
    YOUTUBE_CHANNEL_ID required unless YOUTUBE_HANDLE is set (e.g. UC...)
    YOUTUBE_HANDLE     alternative to the ID (e.g. @nxtlvlmarine)

KNOWN LIMITATION — subscriber counts are rounded.
YouTube rounds subscriberCount down to 3 significant figures as a matter of
policy: 1,234 is reported as 1,230; 12,345 as 12,300. This is the API's
behavior, not a bug here. Below 1,000 subscribers the count is exact; from
1,000-9,999 it moves in steps of 10, so a day with +3 subscribers may show no
change at all and the growth appears as an occasional jump.

viewCount and videoCount are NOT rounded — those are exact.

If exact subscriber counts matter, the YouTube Analytics API returns them, but
it requires OAuth (a token to keep refreshed) rather than a bare API key.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/channels"


def fetch(timeout=20):
    """Return (followers, views_total, views_28d). Raises RuntimeError on failure."""
    key = os.environ.get("YOUTUBE_API_KEY")
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID")
    handle = os.environ.get("YOUTUBE_HANDLE")

    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set")
    if not channel_id and not handle:
        raise RuntimeError("Set YOUTUBE_CHANNEL_ID or YOUTUBE_HANDLE")

    params = {"part": "statistics", "key": key}
    if channel_id:
        params["id"] = channel_id
    else:
        params["forHandle"] = handle if handle.startswith("@") else "@" + handle

    url = f"{API}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.load(e)
            detail = body.get("error", {}).get("message", "")
        except Exception:
            pass
        # 403 here is nearly always the API not being enabled on the Cloud
        # project, or a key restricted to the wrong referrer/IP.
        raise RuntimeError(f"HTTP {e.code} from YouTube{': ' + detail if detail else ''}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach YouTube: {e.reason}")

    items = payload.get("items") or []
    if not items:
        target = channel_id or handle
        raise RuntimeError(
            f"No channel matched {target!r}. Check the ID/handle — a wrong one "
            f"returns an empty list rather than an error."
        )

    stats = items[0].get("statistics", {})

    if stats.get("hiddenSubscriberCount"):
        # The channel has its subscriber count hidden in YouTube settings, so the
        # API returns 0 rather than the real number. Reporting that 0 as "you have
        # zero subscribers" would be a lie, so record it as missing instead.
        followers = None
    else:
        followers = _int(stats.get("subscriberCount"))

    return followers, _int(stats.get("viewCount")), None


def _int(v):
    return None if v is None else int(v)
