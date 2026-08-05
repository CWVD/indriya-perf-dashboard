# Indriya Performance Dashboard — GitHub build

Auto-refreshing site-speed dashboard. Runs on GitHub's servers (free), publishes a
web page anyone on the team can open. Built because Google Sheets / Drive is blocked
by Zscaler — this route never touches a Google file-share domain.

**Two layers (never mix them in one chart):**
- **Field** = CrUX real-user p75, the long-term trend and the number Google ranks on. Refreshes weekly.
- **Lab** = a PageSpeed Insights test we trigger, the spike/regression tripwire. Refreshes daily.

**How it runs:** GitHub Actions (cron) runs `tracker.py`, which calls the two Google APIs
and writes JSON into `docs/`. GitHub Pages serves `docs/index.html`, which reads that JSON
and draws the charts. The git repo is the storage — it replaces the Google Sheet.

---

## What you touch vs what runs itself

You edit **one section**: the page list at the top of `tracker.py` (`FIELD_TARGETS`, `LAB_TARGETS`).
Everything else runs as-is. After setup, the two workflows refresh on their own; viewers just open one link.

---

## Setup — 7 phases

### Phase 1 — Account
**Why:** clean handover, no office-domain lock.
**Steps:** Use the dedicated Gmail you already made. Sign up / sign in at github.com on that account.
**Verify:** you can see your GitHub dashboard.

### Phase 2 — Create the repo (must be PUBLIC)
**Why:** GitHub Pages on a free account only works from a public repo. That is fine here —
the repo holds only public site-speed numbers and code. The API key is NOT in the repo.
**Steps:** New repository → name it `indriya-perf-dashboard` → **Public** → Create.
**Verify:** empty repo page loads.

### Phase 3 — Upload these files
**Why:** this is the whole app.
**Steps:** On the repo page → **Add file → Upload files** → drag in everything from this folder,
**keeping the folder structure** (`.github/workflows/…` and `docs/…` must stay in those paths) → Commit.
**Verify:** you can see `tracker.py`, `requirements.txt`, a `.github/workflows` folder with two `.yml`
files, and a `docs` folder with `index.html` and two `.json` files.

### Phase 4 — Add the API key as a Secret
**Why:** the key must never sit in a public repo. A Secret is injected only at runtime, on GitHub's servers.
**Steps:** Repo → **Settings → Secrets and variables → Actions → New repository secret**.
Name it exactly `API_KEY`. Paste the key (the one restricted to PageSpeed Insights API + Chrome UX Report API). Save.
**Verify:** you see `API_KEY` listed under repository secrets (value hidden).

### Phase 5 — First run (do this by hand to test)
**Why:** proves the pipeline before trusting the timers.
**Steps:** Repo → **Actions** tab → if prompted, enable workflows → click **Refresh field (weekly trend)**
→ **Run workflow** → Run. Then do the same for **Refresh lab (daily spike check)**.
**Verify:** each run goes green. Click into a run → open the `Fetch …` step → you want to see
`FIELD wrote N rows` / `LAB wrote N rows` with **N greater than 0**. Then check `docs/field_data.json`
and `docs/lab_data.json` in the repo — they should now hold data and show a fresh commit by `github-actions`.

> If **field wrote 0** but lab wrote fine: the `www` vs non-www origin is wrong. Open the live site,
> see what's actually in the address bar after any redirect, and set `FIELD_TARGETS` to match exactly.

### Phase 6 — Turn on Pages (the viewer link)
**Why:** this publishes the dashboard.
**Steps:** Repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch: **main**,
Folder: **/docs** → Save. Wait ~1 minute.
**Verify:** the page reloads with a live URL like `https://YOURNAME.github.io/indriya-perf-dashboard/`.
Open it — you should see the charts. Send this URL to the website team + Alim.

### Phase 7 — Confirm the timers are on
**Why:** this is what makes it self-refreshing.
**Steps:** nothing to do — the two workflows already carry their schedules (lab daily 07:00 IST, field
Monday 02:00 UTC). They start running automatically now that the files are in `main`.
**Verify:** tomorrow, the Actions tab shows a scheduled lab run you didn't start by hand.

---

## Changing the pages tracked
Edit `FIELD_TARGETS` / `LAB_TARGETS` at the top of `tracker.py` in the repo (pencil icon → commit).
Keep `LAB_TARGETS` to ~8 tests or fewer. Adding a staging URL only works if it opens with no login/VPN.

## Troubleshooting
- **Run failed, red X, `HTTP 403` in the log:** the key isn't enabled for one of the two APIs, or the
  Secret name isn't exactly `API_KEY`.
- **Run failed on the commit/push step:** the workflow needs `permissions: contents: write` — it's already
  in both files; don't remove it.
- **`git commit … no changes to commit`:** not an error. Field data was identical to last time (normal
  within a CrUX week); the run still succeeds.
- **Dashboard loads but charts are blank / "No data yet":** you haven't run the workflows yet (Phase 5),
  or field genuinely has no data for a quiet page (normal — lab still covers it).

### If charts don't render on a locked-down machine
The dashboard pulls the charting library from a CDN (`cdnjs.cloudflare.com`). If Zscaler blocks that on
Alim's machine, the page loads but charts stay empty. Fix: download `chart.umd.min.js` from that CDN,
add it into `docs/`, and change the one `<script src="…">` line in `index.html` to `src="chart.umd.min.js"`.
Then it's served from your own github.io page, same origin as the dashboard.

## Notes for the handover / IT
- The repo is **public** and contains only public performance data + code. **No credentials** are in it.
- The **API key** is a GitHub Secret, restricted to two free read-only Google APIs, no billing card attached.
- Not built in v1: email alerts on a spike (phase-2 add-on). v1 shows a spike as a visible line-jump in the lab chart.
- Lab history grows slowly (~24 rows/day). Not a concern for a stint; trim `docs/lab_data.json` if it ever gets large.
