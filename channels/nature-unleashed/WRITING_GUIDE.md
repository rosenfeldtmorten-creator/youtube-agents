# Writing guide: Nature Unleashed

This is the brief for the scheduled writing task. Follow it exactly.

## Your job each run

1. Read every file in `queue/`, `published/` and `rejected/` (the `_rejected.reason` field says why a Short failed).
2. Keep the queue at **7 Shorts** (a week, as one goes up every day). Write as many new ones as are missing. If the queue already has 7, stop.
3. Save each one as `queue/<YYYY-MM-DD>-<slug>.json`, dated the day after the last queued one. Any queued Short is a reference for the format.
4. Run `python -m yta check --channel nature-unleashed` and fix every failure until all queued Shorts pass.
5. Commit only the new files in `channels/nature-unleashed/queue/`, with a message like `Queue 2 nature Shorts`, then push to `main`.

Never edit `published/`, `compilations/`, code or `channel.yaml`, and never delete a queued Short you did not write in this run.

## What the channel is

Cool, dramatic moments of nature: landslides, avalanches, lightning, tornadoes, hail, floods, giant waves, volcanoes, wildfires, auroras, waterfalls. Each Short tells **one moment** in under a minute and leaves the viewer with one thing they didn't know. It is not a science lecture: no equations, no jargon without a plain word next to it, no lists of figures. Think "a friend showing you a clip and telling you the wild story behind it".

Good topics:
- A record or famous event: "The Biggest Landslide Ever Recorded" (Mount St. Helens, 1980), "The Wave That Proved Rogue Waves Are Real".
- A "how does that even happen" question: "Why Volcanoes Make Their Own Lightning", "How Hailstones Grow So Big".
- A survival rule people get wrong: "What To Do If You Hear Thunder".

Mix the subjects: never two Shorts in a row about the same thing (two lightning Shorts, two volcano Shorts).

## The rules that keep the channel safe

**Footage.** The video finds its footage itself from the searches you give. It only ever uses free stock video (Pexels, Pixabay) and public-domain or freely licensed footage (NASA, and USGS and NOAA footage on Wikimedia Commons). Never put a link to a news clip, a YouTube video or a viral video in an item, and never describe a clip as if it were a specific filmed event ("watch this car get swept away") unless the search names that exact public-domain footage. The narration tells the real story; the footage shows the kind of thing it is about.

**Our own words.** Every second has our narration on top. YouTube counts that, not the footage, as what makes the channel original. Explain *why* and *how*, never just "look at this".

**True facts only.** There is no data check on this channel, so you are the check. Use only well-established facts you can find on USGS, NOAA, NASA, the national weather services, or a major encyclopaedia. Round numbers ("about 1,200", "up to 250 kilometres an hour"). If sources disagree, use the cautious figure or leave the number out. Never invent a death toll, a record or a quote.

**No clickbait wording.** The check rejects "you won't believe", "shocking", "insane", "gone wrong", "caught on camera" and "viral". Titles should make people curious and the Short must deliver exactly what the title promises.

**No "subscribe" in the script.** The video adds its own spoken and on-screen subscribe prompt; the check rejects a script that says it.

## The shape of every Short

Viewers swipe away in the first two seconds, so:

1. **Hook (first sentence, at most 14 words).** The most surprising fact, said straight away, over the most dramatic clip. "This bolt is about five times hotter than the surface of the Sun." Never a greeting, never "Did you know".
2. **The story (3-6 more scenes).** One or two short sentences per scene, one idea each. Build towards the answer.
3. **The payoff (last scene).** The answer, or the one thing to remember. End on a line that feels finished. The spoken subscribe line is added after it.

Totals: **70-140 words** and **4-8 scenes**, with at most 30 words in a scene. That runs about 30-50 seconds with the outro.

Write for the ear: short sentences, everyday words, a change of pace every few lines. Write plain numbers as digits ("1,200", "1980") and units in words ("kilometres an hour", "degrees Celsius", "metres"); the captions show digits in yellow. Use metric units.

## Footage searches

Each scene's `video` is a list of searches, tried in order until one finds a clip. Give two or three, from specific to general, in plain English as you'd type them into a stock-video site:

    "video": ["lightning strike night", "thunderstorm lightning", "storm clouds"]

- Describe what is on screen, not the idea: "lava flow night", not "volcanic heat".
- End every list with a general search that is sure to find something ("storm clouds", "ocean waves", "volcano").
- Give each scene different searches, so the Short isn't the same clip over and over.
- For named public-domain footage on Wikimedia Commons, a specific search works: "mount st helens eruption", "USGS debris flow".

## Fields

```json
{
  "slug": "lightning-hotter-than-the-sun",
  "title": "Lightning Is Hotter Than the Surface of the Sun",
  "description": "Two or three plain sentences on what the Short explains.",
  "tags": ["lightning", "thunderstorm", "weather", "nature", "science facts"],
  "hashtags": ["Lightning", "Nature", "Weather"],
  "comment": "A question for viewers, posted as the first comment.",
  "scenes": [
    {"narration": "This bolt is about five times hotter than the surface of the Sun.",
     "video": ["lightning strike night", "lightning storm", "storm clouds"]}
  ]
}
```

- `title`: at most 70 characters, in Title Case. It is shown at the top of the Short the whole time.
- `tags`: 5-10, the words people search for. `hashtags`: 2-3, without the `#`.
- `comment`: a question people can answer in a few words ("Have you ever been in a hail storm?").
- Optional `music`: a Kevin MacLeod track title from incompetech.com, if a Short needs a particular mood.

## The weekly compilation

Nothing to write. Once a week the pipeline joins the Shorts that have gone up since the last compilation into one 6-10 minute landscape video, with chapters, a spoken intro and the subscribe ask in the first minute. Good Shorts make a good compilation, so each Short should also make sense on its own when watched back to back with others.
