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

Viewers decide in the first fifteen seconds whether to stay, so every episode is told as a story with a question that only the end answers, not as a lecture. Every episode follows this shape:

1. **Cold open (first scene, at most three sentences, about fifteen seconds).** Start with the single most surprising result, said in terms of the viewer's own life ("In nineteen eighty-four, a typical home cost {{ ... | years }} of pay. Today it costs {{ ... | years }}.", with every number a placeholder as always), over the most dramatic chart (it can be the same chart again later). End it with an open loop: the question the video will answer, which the viewer can only resolve by watching ("So who took the difference? The answer isn't who you think."). Never "In this video we will...", never a channel greeting.
2. **News hook (chapter "What just happened").** A `headlines` montage: 1-3 real headlines about the news, copied word for word with the outlet and date, sliding in one after another over a blurred photo. Keep its narration to one or two sentences, then continue on a photo card.
    Open on something that happened in the last two weeks: a data release, a central bank decision, a company or government announcement. Search the news before writing and say when and who ("On Thursday the Labor Department said..."). Write dates in words ("the sixteenth of October"), never digits. Any number from the news goes in an `inline` series whose `citation` names the outlet and date, so it is still a placeholder.
3. **A person to follow.** Pick one typical person and carry them through the numbers ("Take someone earning the median wage in nineteen eighty-four..."). Always make clear they are an example built from the data, never a real named person. Viewers remember a person far better than a statistic.
4. **The data and the model, with turns.** The charts, with at least one model chart where it fits (see below), and real photos between them. Build towards the strangest finding instead of showing it first in the middle. End most chapters with one short line that pulls into the next ("But that's not the strangest part."). Each tease must be paid off in the very next chapter; never tease what the video doesn't show.
5. **The payoff.** Answer the cold open's question in plain words, with its number, before the take.
6. **My take (last chapter, named "My take").** Two to four honest sentences: what the numbers mean for an ordinary household, and what would change your mind. Opinion, never advice.

Write for the ear: short sentences, one idea each, questions the viewer would ask out loud, and a change of pace every few sentences (a short punchy line after a long one).

## Experiments: titles, thumbnails, stories

The channel is new, so we are finding out what gets clicked and watched. Every episode tries a named style for each of these three and records them in `"experiment": {"title": "...", "thumbnail": "...", "story": "..."}`. Use the style names below so results can be compared, or add a new name when you invent a new style.

**Honesty rule.** Titles and thumbnails should make people curious, but the video must deliver exactly what they promise. No false claims, no fake urgency ("before it's too late"), no promise the data doesn't support. YouTube removes misleading titles and thumbnails, and viewers who feel tricked leave in the first seconds, which hurts more than a dull title.

Title styles (at most 70 characters reads fully on a phone):
- `curiosity-gap`: hides the answer ("The Real Reason Your Rent Keeps Going Up")
- `shock-number`: leads with the striking result in words ("Homes Cost Twice As Many Years Of Pay As In 1984")
- `you-question`: asks about the viewer's own money ("Are You Actually Richer Than Your Parents Were?")
- `myth-buster`: names a common belief and challenges it ("Renting Isn't Throwing Money Away. The Data Says...")
- `versus`: a contest ("Stocks vs Homes vs Bonds: 40 Years, One Winner")
- `then-vs-now`: a year against today ("What $1 From Your Birth Year Is Worth Today")

Title case and up to one year or number are fine in the title (it is not narration).

Thumbnail styles:
- `text`: three to five big words over the chart (the default).
- `badge`: the words plus a big computed number in a coloured box, with `"thumbnail_badge": "{{ pct_change(homes, \"1984-01\", \"latest\") | pct_sign }}"`. Badge formats: `pct_sign` (+337%), `usd_short` ($1.2T), `times_short` (3.4x); at most nine characters once filled.
- `chart`: pick the most dramatic chart as the background with `"thumbnail_scene": <scene number>` (otherwise the first chart is used).
`thumbnail_text` should add to the title, not repeat it ("THEY LIED?" is not allowed; "HOMES vs PAY" is).

Story styles: `cold-open` (the shape above), `countdown` (three or four findings, saving the biggest for last), `myth-vs-reality` (state the belief, test it chart by chart), `one-person` (follow one typical person's life through the decades), `mystery` (start from a strange chart and investigate why). All of them keep the cold open, the news hook and the take.

**How to choose.** Until there are view numbers, rotate so each new episode tries a combination not used in the last three. Once `channels/money-charts/STATS.md` exists, check it before writing: two of every three new episodes use the title, thumbnail and story styles with the most views per video after seven days, and the third tries something different. Shorts titles can carry a `"style"` too, using the same title style names.

## Photos

Put 2-4 `photo` scenes between charts so the video is not only charts: a real place, object or person the narration is about (the Federal Reserve building, a supermarket checkout, a 1968 picket line). Each one shows with a slow zoom, a caption and an on-screen credit, and is credited in the description.

- `{"type": "photo", "query": "Marriner S. Eccles Federal Reserve Board Building", "caption": "The Federal Reserve, Washington"}` searches Wikimedia Commons and takes the first landscape photo with a free licence (public domain, CC0, CC BY or CC BY-SA).
- Add `"after": 2018` to a `query` to skip photos taken before that year, so a story about today's prices doesn't show a 1970s pump.
- `"file": "File:Exact name.jpg"` instead of `query` picks one Commons file exactly. Prefer this when you know a good one.
- Keep a photo scene short (one to three sentences). If no free photo is found, the video shows the caption on a card instead, so the render never fails. A card's `"photo"` can also be a list of searches, tried in order; give two or three, because Commons search is loose (a search for "office workers" once returned a bar called The Office). If none finds a photo, the card reuses the previous photo.

## Footage

Real moving video makes the episode feel like a documentary, so give about half of the `photo` scenes and photo `card`s a `"video"`: one stock-footage search, or a list of two tried in order (`"video": ["suburban street drone", "suburban neighborhood"]`). Keep the photo fields too: if no clip is found, the photo is used, so a render never fails.
- Search for generic, everyday shots that stock libraries have: "counting dollar bills", "supermarket aisle", "house construction site", "stock market ticker screen", "commuters walking city street". A specific place or person (the Federal Reserve building, Paul Volcker) stays a photo.
- Clips come from Pexels and Pixabay (when their free keys are set) and Wikimedia Commons, only with licences that allow reuse, and are credited on screen and in the description. Never use clips cut from other YouTube videos or TV.
- A clip is cropped to fill the frame, slowed slightly if it is short, and a card's title shows over it for three seconds as with photos.

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
- `card`: `title` and optional `label`, for big statements. **No text may sit on screen for long:** a card with more than 12 words of narration needs a `photo` (a search string, or `{"query": ..., "after": 2015}`). The title then shows over the dimmed photo for 3 seconds and fades, and the photo keeps moving.
- `headlines`: `headlines` = 1-5 of `{"source": "Reuters", "date": "2026-10-16", "text": "the exact headline"}` (at most 120 characters each), optional `photo` for the blurred background. Never invent or reword a headline; use only ones you have read.
- `photo`: a real photo, see Photos above. Photos don't count towards the 4 charts.

Every chart has a short `title` (no typed numbers) and may have a `subtitle` explaining units.

## Fields

`slug`, `title` (at most 100 characters, a question or a clear promise, no placeholders), `description` (2 short paragraphs: what happened and what the video answers), `tags` (8-10), `hashtags`, `method`, `references`, `thumbnail_text` (at most 5 words), `experiment`, optional `thumbnail_badge` and `thumbnail_scene`, `data`, `claims`, `scenes` (each `narration` + `chart`).

## Shorts

The channel posts one Short a day, cut from videos that are already up, so each episode should give four or five.
- `short` (`{"title", "scenes"}`) goes up with the video on its launch day. Pick the most surprising chart.
- `shorts` is a list of the same shape for the following days, best first. Give three or four, each one chart scene that makes sense on its own (under about 115 words of narration; a leading "But" or "And" is dropped automatically). Titles are hooks of at most 90 characters, a question or a surprise, with no typed numbers ("Today's minimum wage buys about half as much").
- Chart scenes not listed are used last, titled with the chart's own title.

## Comment

`comment` is the channel's first comment under the video: one question viewers can answer in a few words about their own life ("What year were you born?"), at most 300 characters. It is posted automatically; without it the channel's `default_comment` is used.

## Callouts

A line chart can mark moments on the line itself: `"annotations": [{"date": "2008-09", "text": "Lehman collapses"}]` (optional `"series"` names which line; the first by default). Each callout appears as the line reaches it. Use two or three per chart at most, for events the narration mentions, with at most four words each.
