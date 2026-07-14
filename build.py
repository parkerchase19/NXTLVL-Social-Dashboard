#!/usr/bin/env python3
"""Render data/history.json into a self-contained docs/index.html dashboard.

No dependencies, no chart library, no external requests: the output is one HTML
file with inline SVG and inline CSS/JS, so it renders on GitHub Pages, from a
file:// URL, or offline.

    python3 build.py
"""

import html
import json
import os
from datetime import datetime, timezone

from store import PLATFORM_LABELS, PLATFORM_NOTES, PLATFORMS, load_history

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "docs", "index.html")

BRAND = "nxtlvl Marine"

# Validated categorical palette (slots 1-4). Not brand colors: brand red would
# collide with the reserved status red, and the IG gradient / TikTok black fail
# contrast. Identity is carried by the legend swatch + direct end-label too, so
# color is never the only channel.
SERIES = {
    "instagram": {"light": "#2a78d6", "dark": "#3987e5"},  # blue
    "youtube": {"light": "#1baf7a", "dark": "#199e70"},  # aqua
    "tiktok": {"light": "#eda100", "dark": "#c98500"},  # yellow
    "facebook": {"light": "#008300", "dark": "#008300"},  # green
}


# ---------------------------------------------------------------- data shaping


def series_for(snapshots, platform, field):
    """[(date, value)] for one platform/field, skipping missing points."""
    out = []
    for snap in snapshots:
        p = snap["platforms"].get(platform) or {}
        v = p.get(field)
        if v is not None:
            out.append((snap["date"], v))
    return out


def connected(snapshots, platform):
    """A platform counts as connected once it has ever returned a follower count."""
    return bool(series_for(snapshots, platform, "followers"))


def latest(points):
    return points[-1][1] if points else None


def forward_filled_totals(snapshots):
    """Total followers per date, carrying each platform's last known value forward.

    Without the carry-forward, a platform that fails to report on one run silently
    drops out of the sum, and the dashboard shows a huge fake decline on a day when
    nothing actually happened. A missing reading means "we didn't hear from them",
    not "those followers vanished" — so we hold the last number we trust.
    """
    last_seen = {}
    out = []
    for snap in snapshots:
        for p in PLATFORMS:
            v = (snap["platforms"].get(p) or {}).get("followers")
            if v is not None:
                last_seen[p] = v
        if last_seen:
            out.append((snap["date"], dict(last_seen)))
    return out


def total_delta_over(totals, days):
    """Change in total followers, counted only across platforms present at BOTH ends
    of the window. Comparing a 4-platform total against a 3-platform total would
    report the day you connect a new account as a surge of organic growth."""
    if len(totals) < 2:
        return None
    last_date, last_vals = totals[-1]
    target = datetime.strptime(last_date, "%Y-%m-%d").timestamp() - days * 86400
    prior = [t for t in totals[:-1] if datetime.strptime(t[0], "%Y-%m-%d").timestamp() <= target]
    base_date, base_vals = prior[-1] if prior else totals[0]
    if base_date == last_date:
        return None
    shared = set(last_vals) & set(base_vals)
    if not shared:
        return None
    return sum(last_vals[p] for p in shared) - sum(base_vals[p] for p in shared)


def delta_over(points, days):
    """Change vs the point closest to `days` ago. None if we lack the history."""
    if len(points) < 2:
        return None
    last_date = datetime.strptime(points[-1][0], "%Y-%m-%d")
    target = last_date.timestamp() - days * 86400
    prior = [p for p in points[:-1] if datetime.strptime(p[0], "%Y-%m-%d").timestamp() <= target]
    base = prior[-1] if prior else points[0]
    if base[0] == points[-1][0]:
        return None
    return points[-1][1] - base[1]


def compact(n):
    if n is None:
        return "—"
    n = float(n)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= limit:
            val = n / limit
            return f"{val:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{int(n):,}"


def signed(n):
    if n is None:
        return None
    return f"+{n:,}" if n >= 0 else f"{n:,}"


# ------------------------------------------------------------------ svg charts


def _scale(points, width, height, pad_l, pad_b, pad_t, y_min, y_max):
    """Map (date, value) points to pixel coords."""
    n = len(points)
    if n == 0:
        return []
    span = (y_max - y_min) or 1
    plot_w = width - pad_l - 12
    plot_h = height - pad_b - pad_t
    xs = []
    for i, (_, v) in enumerate(points):
        x = pad_l + (plot_w * (i / (n - 1)) if n > 1 else plot_w / 2)
        y = pad_t + plot_h - ((v - y_min) / span) * plot_h
        xs.append((x, y))
    return xs


def _nice_ticks(y_min, y_max, count=4):
    """Round tick values for the y-axis."""
    span = (y_max - y_min) or 1
    raw = span / count
    mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    step = max(1, round(raw / mag) * mag)
    start = (int(y_min) // step) * step
    ticks = []
    v = start
    while v <= y_max + step:
        if v >= y_min - step:
            ticks.append(v)
        v += step
    return ticks


def line_chart(all_series, width=760, height=300):
    """Multi-series line chart. all_series: [(platform, [(date, value)])]."""
    live = [(p, pts) for p, pts in all_series if len(pts) >= 1]
    if not live:
        return '<p class="empty">No follower history yet — the first collection run will populate this.</p>'

    values = [v for _, pts in live for _, v in pts]
    dates = sorted({d for _, pts in live for d, _ in pts})
    if len(dates) < 2:
        return (
            '<p class="empty">Only one day of data so far. Trend lines appear once '
            "the collector has run on at least two different days.</p>"
        )

    lo, hi = min(values), max(values)
    headroom = (hi - lo) * 0.12 or max(1, hi * 0.05)
    y_min, y_max = max(0, lo - headroom), hi + headroom

    pad_l, pad_b, pad_t = 56, 34, 16
    ticks = _nice_ticks(y_min, y_max)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="chart" role="img" '
        f'aria-label="Followers over time by platform">'
    ]

    # gridlines + y ticks — solid hairlines, recessive
    for t in ticks:
        if not (y_min <= t <= y_max):
            continue
        y = pad_t + (height - pad_b - pad_t) * (1 - (t - y_min) / ((y_max - y_min) or 1))
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - 12}" y2="{y:.1f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{pad_l - 10}" y="{y + 4:.1f}" class="tick" text-anchor="end">{compact(t)}</text>'
        )

    # x labels: first and last only, so they never collide
    parts.append(f'<text x="{pad_l}" y="{height - 12}" class="tick">{dates[0]}</text>')
    parts.append(
        f'<text x="{width - 12}" y="{height - 12}" class="tick" text-anchor="end">{dates[-1]}</text>'
    )

    # one line per platform, 2px, round caps; 8px end dot with a 2px surface ring
    for platform, pts in live:
        coords = _scale(pts, width, height, pad_l, pad_b, pad_t, y_min, y_max)
        if len(coords) >= 2:
            d = " ".join(
                ("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(coords)
            )
            parts.append(f'<path d="{d}" class="line s-{platform}" fill="none"/>')
        ex, ey = coords[-1]
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4.5" class="dot s-{platform}"/>')
        # direct end-label — mandatory at 4 series
        parts.append(
            f'<text x="{ex - 10:.1f}" y="{ey - 10:.1f}" class="endlabel" text-anchor="end">'
            f"{compact(pts[-1][1])}</text>"
        )

    parts.append("</svg>")
    return "".join(parts)


def sparkline(points, platform, width=140, height=36):
    if len(points) < 2:
        return f'<svg viewBox="0 0 {width} {height}" class="spark" aria-hidden="true"></svg>'
    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(points)
    coords = [
        (width * (i / (n - 1)), height - 4 - ((v - lo) / span) * (height - 8))
        for i, (_, v) in enumerate(points)
    ]
    d = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(coords))
    ex, ey = coords[-1]
    return (
        f'<svg viewBox="0 0 {width} {height}" class="spark" aria-hidden="true">'
        f'<path d="{d}" class="sparkline s-{platform}" fill="none"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" class="dot s-{platform}"/>'
        f"</svg>"
    )


# -------------------------------------------------------------------- sections


def stat_tiles(snapshots):
    tiles = []
    for p in PLATFORMS:
        label = PLATFORM_LABELS[p]
        term = PLATFORM_NOTES[p]["followers_term"]
        if not connected(snapshots, p):
            tiles.append(
                f'<div class="tile tile--off">'
                f'<div class="tile__label"><span class="swatch s-{p}"></span>{label}</div>'
                f'<div class="tile__value tile__value--off">Not connected</div>'
                f'<div class="tile__delta">Add credentials to start tracking</div>'
                f"</div>"
            )
            continue
        pts = series_for(snapshots, p, "followers")
        d30 = delta_over(pts, 30)
        d_txt = (
            f'<span class="delta {"up" if d30 >= 0 else "down"}">{signed(d30)}</span> vs 30 days ago'
            if d30 is not None
            else '<span class="delta-none">Baseline — no comparison yet</span>'
        )
        tiles.append(
            f'<div class="tile">'
            f'<div class="tile__label"><span class="swatch s-{p}"></span>{label} · {term}</div>'
            f'<div class="tile__value">{compact(latest(pts))}</div>'
            f'<div class="tile__delta">{d_txt}</div>'
            f'{sparkline(pts[-12:], p)}'
            f"</div>"
        )
    return "".join(tiles)


def views_panels(snapshots):
    """Small multiples — each platform's views on its OWN scale, with its own
    definition stated. Deliberately not summed: the underlying metrics differ."""
    panels = []
    for p in PLATFORMS:
        field = PLATFORM_NOTES[p]["views_field"]
        term = PLATFORM_NOTES[p]["views_term"]
        pts = series_for(snapshots, p, field)
        label = PLATFORM_LABELS[p]
        if not pts:
            panels.append(
                f'<div class="panel panel--off">'
                f'<div class="panel__label"><span class="swatch s-{p}"></span>{label}</div>'
                f'<div class="panel__value">—</div>'
                f'<div class="panel__term">{term}</div></div>'
            )
            continue
        d30 = delta_over(pts, 30)
        sub = (
            f'<span class="delta {"up" if d30 >= 0 else "down"}">{signed(d30)}</span> vs 30 days ago'
            if d30 is not None
            else '<span class="delta-none">Baseline</span>'
        )
        panels.append(
            f'<div class="panel">'
            f'<div class="panel__label"><span class="swatch s-{p}"></span>{label}</div>'
            f'<div class="panel__value">{compact(latest(pts))}</div>'
            f'<div class="panel__term">{term}</div>'
            f'{sparkline(pts[-12:], p)}'
            f'<div class="panel__delta">{sub}</div>'
            f"</div>"
        )
    return "".join(panels)


def table_view(snapshots):
    rows = []
    for snap in reversed(snapshots[-60:]):
        cells = []
        for p in PLATFORMS:
            d = snap["platforms"].get(p) or {}
            f = d.get("followers")
            cells.append(f"<td>{f:,}</td>" if f is not None else '<td class="na">—</td>')
        rows.append(f'<tr><th scope="row">{snap["date"]}</th>{"".join(cells)}</tr>')
    heads = "".join(f"<th>{PLATFORM_LABELS[p]}</th>" for p in PLATFORMS)
    return (
        f'<table class="table"><caption class="sr-only">Follower counts by platform and date</caption>'
        f'<thead><tr><th scope="col">Date</th>{heads}</tr></thead>'
        f'<tbody>{"".join(rows) or "<tr><td colspan=5 class=na>No data yet</td></tr>"}</tbody></table>'
    )


def legend(snapshots):
    items = []
    for p in PLATFORMS:
        on = connected(snapshots, p)
        cls = "legend__item" + ("" if on else " legend__item--off")
        items.append(
            f'<span class="{cls}"><span class="swatch s-{p}"></span>{PLATFORM_LABELS[p]}'
            f'{"" if on else " (not connected)"}</span>'
        )
    return f'<div class="legend">{"".join(items)}</div>'


def errors_banner(snapshots):
    if not snapshots:
        return ""
    last = snapshots[-1]
    # "not configured" is an expected state, not a failure — the platform's tile
    # already says "Not connected". Banner it and you train yourself to ignore the
    # banner, so a genuinely expired token goes unnoticed.
    broken = [
        (PLATFORM_LABELS[p], err)
        for p in PLATFORMS
        if (err := (last["platforms"].get(p) or {}).get("error"))
        and err != "not configured"
    ]
    if not broken:
        return ""
    items = "".join(f"<li><strong>{n}:</strong> {html.escape(str(e))}</li>" for n, e in broken)
    return (
        f'<div class="banner" role="status"><div class="banner__title">'
        f"Some platforms didn’t report on the last run</div><ul>{items}</ul></div>"
    )


# ----------------------------------------------------------------------- shell


def render(history):
    snapshots = history["snapshots"]
    followers = [(p, series_for(snapshots, p, "followers")) for p in PLATFORMS]

    totals = forward_filled_totals(snapshots)
    total = sum(totals[-1][1].values()) if totals else 0
    total_delta = total_delta_over(totals, 30)

    hero_delta = (
        f'<span class="delta {"up" if total_delta >= 0 else "down"}">{signed(total_delta)}</span>'
        f" over the last 30 days"
        if total_delta is not None
        else '<span class="delta-none">Collecting baseline — deltas appear after a few days</span>'
    )

    updated = snapshots[-1]["date"] if snapshots else "never"
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    swatch_css = "\n".join(
        f".s-{p} {{ --c: {c['light']}; }}" for p, c in SERIES.items()
    )
    swatch_css_dark = "\n".join(f".s-{p} {{ --c: {c['dark']}; }}" for p, c in SERIES.items())

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{BRAND} — Social Dashboard</title>
<style>
:root {{
  color-scheme: light dark;
  --surface-1: #fcfcfb;
  --plane: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --good: #006300;
  --crit: #d03b3b;
{swatch_css}
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    --surface-1: #1a1a19;
    --plane: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --good: #0ca30c;
    --crit: #e66767;
{swatch_css_dark}
  }}
}}
:root[data-theme="dark"] {{
  --surface-1: #1a1a19;
  --plane: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --muted: #898781;
  --grid: #2c2c2a;
  --axis: #383835;
  --border: rgba(255,255,255,0.10);
  --good: #0ca30c;
  --crit: #e66767;
{swatch_css_dark}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 32px 20px 64px;
  background: var(--plane); color: var(--text-primary);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}}
.wrap {{ max-width: 940px; margin: 0 auto; }}
header {{ margin-bottom: 28px; }}
h1 {{ font-size: 20px; margin: 0 0 4px; letter-spacing: -0.01em; }}
.sub {{ color: var(--text-secondary); font-size: 13px; margin: 0; }}
h2 {{ font-size: 15px; margin: 36px 0 12px; letter-spacing: -0.005em; }}
h2 .note {{ font-weight: 400; color: var(--muted); font-size: 13px; }}
.card {{
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px;
}}
.hero {{ margin-bottom: 8px; }}
.hero__label {{ color: var(--text-secondary); font-size: 13px; margin-bottom: 6px; }}
.hero__value {{ font-size: 52px; font-weight: 600; line-height: 1.05; letter-spacing: -0.02em; }}
.hero__delta {{ color: var(--text-secondary); font-size: 13px; margin-top: 6px; }}
.delta.up {{ color: var(--good); font-weight: 600; }}
.delta.down {{ color: var(--crit); font-weight: 600; }}
.delta-none {{ color: var(--muted); }}
.grid-tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
.tile, .panel {{
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px;
}}
.tile__label, .panel__label {{
  display: flex; align-items: center; gap: 7px;
  color: var(--text-secondary); font-size: 12px; margin-bottom: 8px;
}}
.tile__value {{ font-size: 28px; font-weight: 600; letter-spacing: -0.01em; }}
.panel__value {{ font-size: 24px; font-weight: 600; letter-spacing: -0.01em; }}
.tile__value--off {{ font-size: 15px; font-weight: 500; color: var(--muted); }}
.tile__delta, .panel__delta {{ color: var(--text-secondary); font-size: 12px; margin-top: 4px; }}
.panel__term {{ color: var(--muted); font-size: 11px; margin-top: 2px; }}
.tile--off, .panel--off {{ border-style: dashed; }}
.swatch {{ width: 9px; height: 9px; border-radius: 2px; background: var(--c, var(--muted)); flex: none; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 16px; margin-top: 14px; }}
.legend__item {{ display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--text-secondary); }}
.legend__item--off {{ color: var(--muted); }}
.legend__item--off .swatch {{ opacity: 0.35; }}
.chart {{ width: 100%; height: auto; display: block; overflow: visible; }}
.chart-scroll {{ overflow-x: auto; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.tick {{ fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }}
.line {{ stroke: var(--c); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.sparkline {{ stroke: var(--c); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
.dot {{ fill: var(--c); stroke: var(--surface-1); stroke-width: 2; }}
.endlabel {{ fill: var(--text-secondary); font-size: 11px; font-weight: 600; }}
.spark {{ width: 100%; height: 36px; margin-top: 10px; display: block; }}
.grid-panels {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
.table {{ width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }}
.table th, .table td {{ text-align: right; padding: 7px 10px; border-bottom: 1px solid var(--grid); }}
.table th[scope=row] {{ text-align: left; font-weight: 400; color: var(--text-secondary); }}
.table thead th {{ text-align: right; color: var(--muted); font-weight: 500; font-size: 12px; }}
.table thead th:first-child {{ text-align: left; }}
.table .na {{ color: var(--muted); }}
details {{ margin-top: 36px; }}
summary {{ cursor: pointer; font-size: 14px; font-weight: 600; padding: 6px 0; }}
.table-wrap {{ overflow-x: auto; margin-top: 12px; }}
.empty {{ color: var(--muted); font-size: 13px; margin: 24px 0; text-align: center; }}
.banner {{
  background: var(--surface-1); border: 1px solid var(--border);
  border-left: 3px solid #fab219; border-radius: 8px;
  padding: 12px 16px; margin-bottom: 20px; font-size: 13px;
}}
.banner__title {{ font-weight: 600; margin-bottom: 4px; }}
.banner ul {{ margin: 0; padding-left: 18px; color: var(--text-secondary); }}
.sr-only {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }}
footer {{ margin-top: 40px; color: var(--muted); font-size: 12px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{BRAND}</h1>
    <p class="sub">Social reach across all platforms · data through {updated}</p>
  </header>

  {errors_banner(snapshots)}

  <div class="card hero">
    <div class="hero__label">Total followers, all platforms</div>
    <div class="hero__value">{compact(total) if snapshots else "—"}</div>
    <div class="hero__delta">{hero_delta}</div>
  </div>

  <h2>By platform</h2>
  <div class="grid-tiles">{stat_tiles(snapshots)}</div>

  <h2>Follower growth</h2>
  <div class="card">
    <div class="chart-scroll">{line_chart(followers)}</div>
    {legend(snapshots)}
  </div>

  <h2>Views <span class="note">— each platform on its own scale</span></h2>
  <p class="sub" style="margin-bottom:12px">
    These are not added together on purpose: YouTube and TikTok report lifetime totals
    while Instagram and Facebook report a rolling 28-day window. Summing them would
    produce a number that means nothing.
  </p>
  <div class="grid-panels">{views_panels(snapshots)}</div>

  <details>
    <summary>Table view — every follower number</summary>
    <div class="table-wrap">{table_view(snapshots)}</div>
  </details>

  <footer>
    Built {built} · {len(snapshots)} snapshot{"s" if len(snapshots) != 1 else ""} on record
  </footer>
</div>
</body>
</html>
"""


def main():
    history = load_history()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write(render(history))
    print(f"Wrote {OUT_PATH} ({len(history['snapshots'])} snapshots)")


if __name__ == "__main__":
    main()
