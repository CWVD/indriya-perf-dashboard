"""
INDRIYA PERFORMANCE MONITORING  -  GitHub Actions version (field + lab)

FIELD  (real users, long-term trend)  ->  CrUX History API     ->  docs/field_data.json
LAB    (fresh test, catches spikes)    ->  PageSpeed Insights   ->  docs/lab_data.json

This is the same two-layer logic as the Apps Script version, ported to Python
so it runs on GitHub's servers instead of inside a Google Sheet.

You only edit the CONFIG section below. Everything under the line runs as-is.
The API key is NOT in this file -- it is read from a GitHub Secret at runtime.

Run modes (the workflow decides which one to call):
    python tracker.py field   -> refreshes the trend file  (weekly)
    python tracker.py lab      -> appends a spike snapshot  (daily)
"""

import os
import sys
import json
import datetime
import requests

# ============================================================
#  CONFIG  -  YOUR PAGES  (this is the only part you edit)
# ============================================================

# FIELD = real-user data (the trend line, the number that affects Google ranking).
#   type 'origin' = the whole website (one combined number).
#   type 'url'    = one specific page. Only works if the page gets enough traffic;
#                   quiet pages return nothing (that is normal -- LAB still covers them).
#   label / kind  = friendly name + page type, used only for display on the dashboard.
#
# IMPORTANT: the origin/url must EXACTLY match what real users load in the address
# bar (www vs non-www, https). If field comes back empty, this is almost always why.
#   FIELD only holds pages that actually have real-user data: the whole-site
#   origin, the homepage, and busy category (PLP) pages. Product and store pages
#   almost never clear CrUX's traffic threshold, so they are NOT in Field -- they
#   live in Lab below, which works regardless of traffic. (If you add a PDP/store
#   here it will simply come back empty; that is expected, not a bug.)
FIELD_TARGETS = [
    # Whole site -- the complete-website number. Always has data. (Canonical is www.)
    {"type": "origin", "value": "https://www.indriya.com",                  "label": "Whole site (all pages)", "kind": "Origin"},
    # Homepage
    {"type": "url",    "value": "https://www.indriya.com/",                 "label": "Homepage",               "kind": "Homepage"},
    # PLP -- category listing pages (usually have field data)
    {"type": "url",    "value": "https://www.indriya.com/jewellery/rings",    "label": "Rings (PLP)",     "kind": "PLP"},
    {"type": "url",    "value": "https://www.indriya.com/jewellery/neckwear", "label": "Necklaces (PLP)", "kind": "PLP"},
]

# LAB = a fresh speed test we trigger ourselves (the spike / early-regression detector).
#   ANY publicly reachable URL works -- including a staging URL, BUT ONLY IF that
#   staging URL opens in a normal browser with no login / no VPN.
#   (No 'origin' here -- a lab test needs a real page URL, so Lab starts at the homepage.)
#   This is the full page-type mix -- homepage + 2 PLP + 2 PDP + 2 store -- so the
#   dashboard covers a complete picture. The PDP URLs below are real, verified
#   product pages; if a product is ever discontinued its URL will 404 (the run log
#   will show "HTTP 404" -- just swap in a fresh product URL from the live site).
LAB_TARGETS = [
    {"value": "https://www.indriya.com/",                                                      "label": "Homepage",                  "kind": "Homepage"},
    {"value": "https://www.indriya.com/jewellery/rings",                                       "label": "Rings (PLP)",               "kind": "PLP"},
    {"value": "https://www.indriya.com/jewellery/neckwear",                                    "label": "Necklaces (PLP)",           "kind": "PLP"},
    {"value": "https://www.indriya.com/jewellery-products/nakshatra-diamond-necklace-deara70-adns713", "label": "Nakshatra Necklace (PDP)", "kind": "PDP"},
    {"value": "https://www.indriya.com/jewellery-products/indu-diamond-necklace-deaya40-apns627",      "label": "Indu Necklace (PDP)",      "kind": "PDP"},
    {"value": "https://www.indriya.com/jewellery-stores",                                      "label": "Store locator",             "kind": "Store"},
    # --- ONE store page to fill in yourself ---------------------------------------
    # Open the live store locator, click ONE specific store to open its own page,
    # copy the full address bar, and paste it below (keep the quotes). Until you do,
    # this line is skipped automatically.
    {"value": "PASTE_ONE_STORE_PAGE_URL_HERE",                                                 "label": "Store page (one branch)",   "kind": "Store"},
    # {"value": "https://staging.indriya.com/", "label": "Staging home", "kind": "Homepage"},  # add ONLY if it opens with no login
]

# Each lab test is slow (~15-40s). 7 pages x 2 devices = 14 tests ~= 5-8 min per run,
# which is fine on GitHub Actions. If you add many more, split into two runs.

# ============================================================
#  ----------  nothing to edit below this line  ----------
# ============================================================

API_KEY = os.environ.get("API_KEY", "")
if not API_KEY:
    print("ERROR: API_KEY environment variable is empty. "
          "Set it as a GitHub Secret named API_KEY.")
    sys.exit(1)

FIELD_FORM_FACTORS = ["PHONE", "DESKTOP"]
LAB_STRATEGIES     = ["mobile", "desktop"]

FIELD_METRICS = [
    "largest_contentful_paint",
    "cumulative_layout_shift",
    "interaction_to_next_paint",
    "first_contentful_paint",
    "experimental_time_to_first_byte",
]
FIELD_PRETTY = {
    "largest_contentful_paint":         "LCP",
    "cumulative_layout_shift":          "CLS",
    "interaction_to_next_paint":        "INP",
    "first_contentful_paint":           "FCP",
    "experimental_time_to_first_byte":  "TTFB",
}

# Google's good / needs-improvement / poor cut-offs
T = {
    "LCP":  {"good": 2500, "poor": 4000},   # ms
    "CLS":  {"good": 0.1,  "poor": 0.25},   # score
    "INP":  {"good": 200,  "poor": 500},    # ms
    "FCP":  {"good": 1800, "poor": 3000},   # ms
    "TTFB": {"good": 800,  "poor": 1800},   # ms
    "TBT":  {"good": 200,  "poor": 600},    # ms  (lab only)
    "SI":   {"good": 3400, "poor": 5800},   # ms  (lab only)
}

HERE = os.path.dirname(os.path.abspath(__file__))
FIELD_FILE = os.path.join(HERE, "docs", "field_data.json")
LAB_FILE   = os.path.join(HERE, "docs", "lab_data.json")


def rate(metric, val):
    if val is None:
        return ""
    if metric == "PerfScore":                 # higher is better
        if val >= 90:
            return "Good"
        if val >= 50:
            return "Needs Improvement"
        return "Poor"
    t = T.get(metric)
    if not t:
        return ""
    if val <= t["good"]:
        return "Good"
    if val <= t["poor"]:
        return "Needs Improvement"
    return "Poor"


def now_iso():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


# ============ FIELD  (CrUX History API) ============
# Overwrites its file every run. Intentional: the History API always returns the
# full ~6-month history, so rewriting keeps it clean with no duplicates.
def refresh_field():
    rows = []
    for target in FIELD_TARGETS:
        for ff in FIELD_FORM_FACTORS:
            body = {"formFactor": ff, "metrics": FIELD_METRICS}
            if target["type"] == "origin":
                body["origin"] = target["value"]
            else:
                body["url"] = target["value"]

            try:
                resp = requests.post(
                    "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord",
                    params={"key": API_KEY},
                    json=body,
                    timeout=60,
                )
            except requests.RequestException as e:
                print(f"FIELD error {target['value']} [{ff}]: {e}")
                continue

            if resp.status_code != 200:
                print(f"FIELD skip {target['value']} [{ff}] HTTP {resp.status_code}")
                continue

            rec = resp.json().get("record", {})
            periods = rec.get("collectionPeriods", [])
            metrics = rec.get("metrics", {})

            for m in FIELD_METRICS:
                mo = metrics.get(m)
                if not mo or "percentilesTimeseries" not in mo:
                    continue
                p75s = mo["percentilesTimeseries"].get("p75s", [])
                for i, raw in enumerate(p75s):
                    if raw is None:
                        continue
                    p = periods[i] if i < len(periods) else None
                    date_str = ""
                    if p and "lastDate" in p:
                        d = p["lastDate"]
                        date_str = f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"
                    name = FIELD_PRETTY[m]
                    val = float(raw)
                    rows.append({
                        "date": date_str,
                        "target": target["value"],
                        "label": target.get("label", target["value"]),
                        "kind": target.get("kind", ""),
                        "formFactor": ff,
                        "metric": name,
                        "p75": val,
                        "rating": rate(name, val),
                    })

    write_json(FIELD_FILE, {"pulledOn": now_iso(), "rows": rows})
    print(f"FIELD wrote {len(rows)} rows.")


# ============ LAB  (PageSpeed Insights API) ============
# APPENDS a new snapshot each run (does NOT wipe), so daily history builds up
# and the dashboard can show a spike as a line that jumps.
def refresh_lab():
    today = datetime.date.today().isoformat()
    new_rows = []

    for tgt in LAB_TARGETS:
        url   = tgt["value"]
        label = tgt.get("label", url)
        kind  = tgt.get("kind", "")
        if "PASTE_" in url:
            print(f"LAB skip {label} (placeholder URL not filled in yet)")
            continue
        for strategy in LAB_STRATEGIES:
            try:
                resp = requests.get(
                    "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                    params={
                        "url": url,
                        "strategy": strategy,
                        "category": "performance",
                        "key": API_KEY,
                    },
                    timeout=120,
                )
            except requests.RequestException as e:
                print(f"LAB error {url} [{strategy}]: {e}")
                continue

            if resp.status_code != 200:
                print(f"LAB skip {url} [{strategy}] HTTP {resp.status_code}")
                continue

            lr = resp.json().get("lighthouseResult")
            if not lr:
                print(f"LAB no result {url}")
                continue
            a = lr.get("audits", {})

            def num(key):
                return (a.get(key) or {}).get("numericValue")

            score = None
            cats = lr.get("categories", {})
            perf = cats.get("performance")
            if perf and perf.get("score") is not None:
                score = round(perf["score"] * 100)

            pairs = [
                ("LCP", num("largest-contentful-paint")),
                ("CLS", num("cumulative-layout-shift")),
                ("TBT", num("total-blocking-time")),
                ("FCP", num("first-contentful-paint")),
                ("SI",  num("speed-index")),
                ("PerfScore", score),
            ]

            for name, val in pairs:
                if val is None:
                    continue
                val = round(val, 3) if name == "CLS" else round(val)
                new_rows.append({
                    "date": today,
                    "target": url,
                    "label": label,
                    "kind": kind,
                    "strategy": strategy,
                    "metric": name,
                    "value": val,
                    "rating": rate(name, val),
                })

    existing = read_json(LAB_FILE, default={"rows": []})
    all_rows = existing.get("rows", []) + new_rows
    write_json(LAB_FILE, {"pulledOn": now_iso(), "rows": all_rows})
    print(f"LAB wrote {len(new_rows)} new rows (total {len(all_rows)}).")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "field":
        refresh_field()
    elif mode == "lab":
        refresh_lab()
    else:
        print("Usage: python tracker.py [field|lab]")
        sys.exit(1)
