# nxtlvl Marine — social dashboard

Tracks followers and views across Instagram, YouTube, TikTok and Facebook.
A daily GitHub Action pulls the numbers, appends a snapshot to `data/history.json`,
rebuilds `docs/index.html`, and publishes it to GitHub Pages.

No servers, no monthly cost, no dependencies — Python standard library only.
Credentials live in GitHub Secrets and never touch the published page.

```
collect.py            pulls today's numbers, appends a snapshot
build.py              renders data/history.json -> docs/index.html
store.py              snapshot schema + history file handling
collectors/           one module per platform
data/history.json     append-only history (the only thing that matters — back it up)
docs/index.html       the dashboard (generated; don't hand-edit)
```

## Status

| Platform | Status | What it needs |
|---|---|---|
| YouTube | **Ready** | An API key. ~5 minutes. |
| Instagram | Not built yet | Meta app + a 60-day token that must be refreshed |
| Facebook | Not built yet | Same Meta app; a non-expiring Page token |
| TikTok | Not built yet | OAuth app in sandbox mode; token rotates on every use |

Unconfigured platforms show as "not connected" and are skipped — the dashboard
works fine with only YouTube on.

---

## Set up YouTube (do this first)

**1. Get an API key**

1. Go to <https://console.cloud.google.com/> and create a project (name it anything).
2. Enable the YouTube Data API v3: <https://console.cloud.google.com/apis/library/youtube.googleapis.com> → **Enable**.
3. Go to **APIs & Services → Credentials → Create Credentials → API key**. Copy it.
4. Optional but wise: click the key → **Restrict key** → under *API restrictions*
   select **YouTube Data API v3**. That way a leaked key can't be used for anything else.

**2. Find your channel ID**

Go to <https://www.youtube.com/account_advanced> while logged in as nxtlvl Marine.
It shows your channel ID (starts with `UC...`). You can use your `@handle` instead,
but the ID is stable — a handle can be changed.

**3. Test it locally**

```bash
export YOUTUBE_API_KEY="your-key-here"
export YOUTUBE_CHANNEL_ID="UC..."

python3 collect.py     # should print your real subscriber count
python3 build.py       # writes docs/index.html
open docs/index.html   # look at it
```

If that shows your real numbers, you're done with the hard part.

**4. Put it on autopilot**

Push this repo to GitHub, then:

- **Settings → Secrets and variables → Actions → New repository secret**
  Add `YOUTUBE_API_KEY` and `YOUTUBE_CHANNEL_ID`.
- **Settings → Pages → Source: GitHub Actions**
- **Actions tab → "Collect social stats" → Run workflow** to trigger the first run
  by hand instead of waiting for the 07:10 UTC cron.

Your dashboard is then live at `https://<your-username>.github.io/<repo-name>/`.

> **Public vs private repo.** On GitHub's free plan, Pages only publishes from a
> **public** repo. Your API key is safe either way (it's in Secrets, not in the repo),
> but a public repo means your follower history is publicly readable. Three options:
> make the repo public and accept that; upgrade to GitHub Pro, which allows Pages from
> a private repo; or keep it private with no Pages and just open `docs/index.html`
> locally after a `git pull`. The collector works identically in all three.

---

## Things that will surprise you

**YouTube rounds subscriber counts.** The API reports subscribers to 3 significant
figures: 1,234 comes back as 1,230. Between 1,000 and 9,999 subscribers your count
only moves in steps of 10, so a day with +3 subs shows as flat and growth arrives in
visible jumps. This is YouTube's policy, not a bug in the collector. View counts and
video counts are exact. Exact subscriber counts need the YouTube *Analytics* API,
which requires OAuth — worth adding later if the rounding bothers you.

**Views are not comparable across platforms, so they are never summed.** YouTube and
TikTok report lifetime cumulative views; Instagram and Facebook report a rolling
28-day window. A single "total views" number across all four would be meaningless, so
the dashboard shows them as separate panels, each labeled with what it actually
measures. Followers *are* comparable, which is why they're the headline.

**A failed API call doesn't mean followers vanished.** If a platform errors, its last
known value is carried forward in the total, and a banner names the platform that
failed. Without that, one expired token would render as a cliff-edge drop in
followers on the chart.

**The history file is the asset.** API keys are replaceable; `data/history.json` is
not — nobody can backfill a follower count from three weeks ago. It's committed to
git on every run, so the repo is the backup.

---

## Adding the other platforms

Each collector is a module in `collectors/` exposing one function:

```python
def fetch():
    """Return (followers, views_total, views_28d). Raise RuntimeError on failure."""
```

`collect.py` finds it automatically once the platform's trigger env var is set
(see `TRIGGER_VARS` in `collect.py`). Return `None` for any metric the platform
doesn't expose.

Notes from the API research, so the next person doesn't rediscover them:

- **Meta (Instagram + Facebook): App Review is not required.** Keep the app in
  Development mode with yourself as admin, reading your own accounts — that's
  Standard Access, which is auto-granted. Review is only needed to read *other
  people's* accounts.
- **Facebook Page reach metrics are a live minefield.** The `page_impressions*`
  family was deprecated in Nov 2025, and Meta's own reference docs contradict their
  changelog about what replaced it. `followers_count` off the Page node is rock
  solid; validate any reach metric in the Graph API Explorer before coding it.
- **Instagram's token expires in 60 days** and must be refreshed while still valid.
  Miss the window and you redo the whole browser auth flow. Refresh on a ~30-day
  cadence, not on day 59.
- **TikTok has a sandbox mode** that avoids app review entirely for your own account —
  the alternative (production review) demands a public website, privacy policy, and
  demo video. Its refresh token **rotates on every use**: persist the new one each
  time or you lock yourself out. The refresh token also hard-expires after 365 days,
  at which point a human must re-authorize. Build the alert for that now.
