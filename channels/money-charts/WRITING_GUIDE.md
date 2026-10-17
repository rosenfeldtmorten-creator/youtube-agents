# Writing guide: Economics in Charts

This is the brief for the scheduled writing task. Follow it exactly.

## Your job each run

1. Read every file in `queue/`, `published/` and `rejected/` (the `_rejected.reason` field says why an episode failed).
2. Keep the queue at **4 episodes**. Write as many new ones as are missing. If the queue already has 4, stop.
3. Save each one as `queue/<YYYY-MM-DD>-<slug>.json`. The queued sample `did-your-paycheck-keep-up` (or its copy in `published/`) is the reference for the format.
4. Run `python -m yta check --channel money-charts`. It downloads the data, fills every placeholder and tests every claim. Fix and re-check until every queued episode passes.
5. Commit only the new files in `channels/money-charts/queue/`, with a message like `Queue 1 money episode`, then push to `main`.

Never edit `published/`, code or `channel.yaml`, and never delete a queued episode you did not write in this run.

## The one rule: never type a number

Every number in the narration and chart titles must be a placeholder that the pipeline computes from the data:

    Prices rose {{ pct_change(cpi, "2000-01", "latest") | pct }} since 2000.

Years such as 2000 may be typed. Everything else, including example amounts, goes in a placeholder: `{{ 200 | usd }}`.
The check rejects any other digit.

**Functions:** `value(s, "2010-06")`, `latest(s)`, `latest_year(s)`, `first(s, start, end)`, `change(s, a, b)`, `pct_change(s, a, b)`, `ratio(s, a, b)`, `cagr(s, a, b)`, `highest(s, a, b)`, `lowest(s, a, b)`, `year_of_highest(s, a, b)`, `year_of_lowest(s, a, b)`, `grow(amount, rate, years)`, `compound(monthly, rate, years)`, `in_todays_money(amount, cpi, "2000-01")`, `payment(principal, rate_percent, years)` (monthly loan payment; pass a FRED rate such as `value(mortgage, "2021")` directly), plus `+ - * /`.

**Model functions** (on yearly averages, the same fit the scatter chart draws): `correlation(x, y, start, end)`, `slope(x, y, start, end)` (how much y moves per one unit of x), `r_squared(x, y, start, end)` (share of y's ups and downs the line explains), `trend_per_year(s, start, end)`.
Dates are `"2000"`, `"2000-06"`, `"2000-06-30"` or `"latest"`.

**Formats** (after `|`): `usd`, `usd_cents`, `pct`, `pct1`, `pts`, `num`, `times`, `year`, `years`.

## Claims

Every comparison or conclusion the script states in words ("pay kept up", "the fastest rise since 1980") must appear in `claims` with a `check` that is true in the data, for example:

    {"says": "Pay rose faster than prices", "check": "ratio(wages, \"2000-01\", \"latest\") > ratio(cpi, \"2000-01\", \"latest\")"}

If new data makes a claim false, the episode is rejected before upload. Write the story the data tells, not the one you expect.

## Data

Use only public series that need no key:

- **FRED** (`"source": "fred", "id": "<series id>"`): for example CPIAUCSL (consumer prices), AHETPI (hourly pay), CSUSHPINSA (house prices), MSPUS (median house price), MORTGAGE30US (mortgage rate), FEDFUNDS, UNRATE, GASREGW (petrol price), DGS10 (10-year Treasury), SP500 (last ten years only), PSAVERT (savings rate), TOTALSL (consumer credit).
- **World Bank** (`"source": "worldbank", "country": "US", "indicator": "NY.GDP.PCAP.CD"`) for country comparisons.
- **Inline** (`"source": "inline", "points": [["2000", 1.5], ...], "citation": "..."`) only for small official tables, or a figure from a news report, that you can cite exactly.

Give each series a `label` (shown in legends) and a `short_source` (shown under charts).

Two optional settings on a series:

- `"transform": "yoy"` turns levels into the change on a year earlier, as a fraction. Use it for inflation from CPI (`y_format: "pct"`).
- `"in_todays_dollars": "cpi"` restates a dollar series in today's money using another series in `data` (here `cpi`). Every function and chart then works on the real values.

**Checking offline.** If the check can't download a series (blocked network), it uses the copy in `data/snapshot/`, refreshed daily from the list in `data/series.json`. Prefer series from that list. A new series gets a snapshot after you push an episode that uses it, so if the check fails only because a snapshot is missing, push the episode anyway; the publish run downloads live data and rejects it if anything is wrong.

## The shape of every episode

Viewers should feel they are watching a sharp news explainer, not a lecture. Every episode follows this shape:

1. **News hook (first scene, chapter "What just happened").** Open on something that happened in the last two weeks: a data release, a central bank decision, a company or government announcement. Search the news before writing and say when and who ("On Thursday the Labor Department said..."). Write dates in words ("the sixteenth of October"), never digits. Any number from the news goes in an `inline` series whose `citation` names the outlet and date, so it is still a placeholder.
2. **The question.** Turn the news into the question a normal person asks about their money.
3. **The data and the model.** The charts, with at least one model chart where it fits (see below), and real photos between them.
4. **My take (last chapter, named "My take").** Two to four honest sentences: what the numbers mean for an ordinary household, and what would change your mind. Opinion, never advice.

## Photos

Put 2-4 `photo` scenes between charts so the video is not only charts: a real place, object or person the narration is about (the Federal Reserve building, a supermarket checkout, a 1968 picket line). Each one shows with a slow zoom, a caption and an on-screen credit, and is credited in the description.

- `{"type": "photo", "query": "Marriner S. Eccles Federal Reserve Board Building", "caption": "The Federal Reserve, Washington"}` searches Wikimedia Commons and takes the first landscape photo with a free licence (public domain, CC0, CC BY or CC BY-SA).
- `"file": "File:Exact name.jpg"` instead of `query` picks one Commons file exactly. Prefer this when you know a good one.
- Keep a photo scene short (one to three sentences). If no free photo is found, the video shows the caption on a card instead, so the render never fails.

## Description fields

The description is built for you in this order: hashtags, `description`, CHAPTERS, HOW WE DID THE MATHS, SOURCES, PHOTOS, MUSIC, hashtags again. Fill these fields:

- `hashtags`: 3-5 words without `#`, most important first (YouTube shows the first three above the title): `["Economics", "Inflation", "Wages"]`.
- `method`: one or two sentences on any calculation that is ours ("We restate every wage in today's dollars with the consumer price index, then fit a straight line through the yearly averages.").
- `references`: every news story or report the script mentions, as `{"source": "Reuters", "date": "2026-10-16", "says": "what it reported", "url": "https://..."}`. The data series are listed automatically.
- `music` (optional): a Kevin MacLeod track title from `yta/music.py`; left out, one is picked for you.

## What makes a good episode

- **One question a normal person asks about money**, answered with data: "Is renting really throwing money away?", "What happened to the price of fuel?", "How much does waiting ten years to invest cost?". Vary topics; never repeat a question already in `published/` or `queue/`.
- 1300-1900 words (the cloned voice reads about 230 words a minute, so this is 6-8 minutes), 8-14 scenes, at least 4 charts. Where it fits the question, include one model chart (`scatter` or a `trend`): the channel's edge is explaining what the data says, not just showing it. Open with the question on a `card`, end with the answer on a `card`.
- Plain spoken English. Explain every term the first time. No hype, no "you should buy", no individual stocks or crypto tips. This channel explains; it never advises.
- Give the scenes that start a new part a `chapter` name (at least 3 per episode) so YouTube shows chapters.

## Chart types

- `line`: `series` (list of data names), `from`, optional `to`, `index` (rebase every series to 100 at that date, needed when units differ), `labels` (legend names), `y_format` (`usd`, `pct`, `num`, `index`), `yearly: true` for long daily series, `log: true` for very long growth, `trend: "linear"` or `"smooth"` to draw a fitted trend line once the data is shown.
- `scatter`: a simple model. `x` and `y` (data names), `from`, optional `to`, `x_format`, `y_format`, `x_label`, `y_label`, `fit` (`linear`, `smooth` or `none`), `connect: true` to join the years in order. One point per year (yearly averages), revealed in time order, then the fitted line with its 95% band. Explain in plain words what the line means, and back any statement about it with `correlation`, `slope` or `r_squared` in `claims`. Say "moved together", never "caused", unless you explain why.
- `bars`: `bars` = list of `{"label": "...", "value": "<expression>"}`, `y_format`.
- `growth`: `monthly`, `rate`, `years` (expressions). Shows money put in versus what it grew to.
- `card`: `title` and optional `label`, for big statements.
- `photo`: a real photo, see Photos above. Photos don't count towards the 4 charts.

Every chart has a short `title` (no typed numbers) and may have a `subtitle` explaining units.

## Fields

`slug`, `title` (at most 100 characters, a question or a clear promise, no placeholders), `description` (2 short paragraphs: what happened and what the video answers), `tags` (8-10), `hashtags`, `method`, `references`, `thumbnail_text` (at most 5 words), `data`, `claims`, `scenes` (each `narration` + `chart`).
