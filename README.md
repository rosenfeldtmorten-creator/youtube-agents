# youtube-agents

Agents that write, narrate, render and upload videos for a set of YouTube channels, automatically and on free tools.

| Channel | Status |
| --- | --- |
| Slow English Stories | Pipeline built; waiting for setup |
| Economics in Charts | Pipeline built; waiting for setup |
| Nature Unleashed | Daily narrated nature Shorts plus a weekly compilation (`format: clips`); waiting for its YouTube login |
| Deep sleep sounds | Planned |

## How it works

1. **Writing.** A scheduled Claude task reads `channels/<channel>/WRITING_GUIDE.md`, writes new items into the channel's `queue/`, checks them, and pushes them here.
2. **Checks.** `python -m yta check` validates every queued item: format, level, length, and similarity to everything already published. Items that fail at publish time move to `rejected/` with the reason.
3. **Rendering.** `python -m yta run` takes the next item, narrates it with a clone of the creator's voice ([Chatterbox](https://github.com/resemble-ai/chatterbox), MIT licence), draws the slides or charts, and builds the video with FFmpeg. Finance charts are drawn in R with ggplot2 (`charts/chart.R`); change their look in `theme_money()`.
   Clips channels (`yta/clips.py`) narrate over licensed stock and public-domain footage (`yta/footage.py`) as vertical Shorts, and `python -m yta compile` joins a week of them into one landscape video (`.github/workflows/compilation.yml`).
   Finance scripts never type numbers: every figure is a `{{ ... }}` placeholder computed from public data (FRED, World Bank), and every comparison made in words is listed under `claims` and checked against the data before upload.
4. **Upload.** The YouTube Data API uploads the video with title, description, chapters, tags, thumbnail and captions, with AI voice disclosure switched on. The item moves to `published/`.
5. **Pacing.** `channel.yaml` caps uploads per week, so the channel never posts faster than a person could.

GitHub Actions runs steps 2-5 daily (`.github/workflows/publish.yml`) once the `AUTOPUBLISH` variable is set.

## Setup

See [docs/SETUP.md](docs/SETUP.md) for the first channel and [docs/NEW_CHANNEL.md](docs/NEW_CHANNEL.md) to add more.

## More channels

Every channel is a folder in `channels/` and shares everything else. `python -m yta new-channel` (or the
**New channel** workflow) makes the folder; you make the channel on YouTube; **Connect channel** gives you a
code to type at google.com/device and saves the login as a secret; **Switch channel** adds it to
`ACTIVE_CHANNELS` for Publish, Daily Short, Prepare voices and Compilation.

## Running it yourself

You don't need to, but it works on any computer with Python 3.11 and FFmpeg:

```bash
pip install -r requirements.txt
python -m yta check --channel english-stories
python -m yta run --channel english-stories --no-upload --voice silent   # test video in out/
```

`--voice chatterbox` needs `pip install -r requirements-voice.txt --extra-index-url https://download.pytorch.org/whl/cpu` and `voice/reference.wav`.

## Layout

```
channels/<channel>/channel.yaml     settings: pacing, voice, YouTube options, level rules
channels/<channel>/WRITING_GUIDE.md brief for the writing task
channels/<channel>/queue/           items waiting to be published
channels/<channel>/published/       items already uploaded, with their YouTube links
channels/<channel>/rejected/        items that failed a check, with the reason
yta/                                the pipeline (Python)
charts/chart.R                      finance chart style and animation (R, ggplot2)
voice/reference.wav                 10-20 second clip of the narrator
```
