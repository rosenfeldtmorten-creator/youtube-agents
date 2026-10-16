# youtube-agents

Agents that write, narrate, render and upload videos for a set of YouTube channels, automatically and on free tools.

| Channel | Status |
| --- | --- |
| Slow English Stories | Pipeline built; waiting for setup |
| Money, in charts | Planned |
| Deep sleep sounds | Planned |

## How it works

1. **Writing.** A scheduled Claude task reads `channels/<channel>/WRITING_GUIDE.md`, writes new items into the channel's `queue/`, checks them, and pushes them here.
2. **Checks.** `python -m yta check` validates every queued item: format, level, length, and similarity to everything already published. Items that fail at publish time move to `rejected/` with the reason.
3. **Rendering.** `python -m yta run` takes the next item, narrates it with a clone of the creator's voice ([Chatterbox](https://github.com/resemble-ai/chatterbox), MIT licence), draws the slides, and builds the video with FFmpeg.
4. **Upload.** The YouTube Data API uploads the video with title, description, chapters, tags, thumbnail and captions, with AI voice disclosure switched on. The item moves to `published/`.
5. **Pacing.** `channel.yaml` caps uploads per week, so the channel never posts faster than a person could.

GitHub Actions runs steps 2-5 daily (`.github/workflows/publish.yml`) once the `AUTOPUBLISH` variable is set.

## Setup

See [docs/SETUP.md](docs/SETUP.md).

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
voice/reference.wav                 10-20 second clip of the narrator
```
