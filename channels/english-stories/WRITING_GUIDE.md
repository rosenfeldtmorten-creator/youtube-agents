# Writing guide: Slow English Stories

This is the brief for the scheduled writing task. Follow it exactly.

## Your job each run

1. Read every file in `queue/`, `published/` and `rejected/` (the `_rejected.reason` field says why a story failed).
2. Keep the queue at **6 stories**. Write as many new ones as are missing. If the queue already has 6, stop.
3. Save each story as `queue/<YYYY-MM-DD>-<slug>.json`, using today's date. The schema is below; `tests/data/sample-story.json` is a complete example.
4. Run `python -m yta check --channel english-stories`. Fix and re-check until every queued story passes.
5. Commit only the new files in `channels/english-stories/queue/` with a message like `Queue 2 English stories`, then push to `main`.

Never edit `published/`, never change code or `channel.yaml`, and never delete a queued story you did not write in this run.

## What makes a good story

- **One complete, original story** with a clear beginning, problem and ending. Warm, calm and a little surprising. Think short fiction for adults, not children's books.
- **Rotate levels** so the queue holds A2, B1 and B2 roughly equally. Look at the last few published levels and pick the least recent.
- **Vary the world**: different settings (cities, villages, the sea, the past, near future), jobs, ages, and countries. No theme, main character name, or plot shape may repeat anything in `published/` or `queue/`.
- **Language by level** (the checks enforce word counts and sentence length):

| Level | Words | Average words per sentence | Grammar |
| --- | --- | --- | --- |
| A2 | 600-1100 | 11 or fewer | Present and past simple, common words, short sentences |
| B1 | 850-1500 | 15 or fewer | Past continuous, simple conditionals, everyday idioms |
| B2 | 1100-2000 | 20 or fewer | Wider vocabulary, reported speech, mixed tenses |

- Spoken by a narrator, so write for the ear: no lists, no headings, no footnotes, no emoji.
- Avoid abbreviations that end in a full stop (Mr., Dr., etc.). Write "Mister Brown" or "Doctor Lee" instead.
- Write numbers as words when a learner would say them ("forty years").
- Keep content safe for a general audience: no violence beyond mild peril, no politics, religion, brands, or real living people.

## Fields

- `slug`: lowercase words joined with hyphens, unique.
- `title`: `<Story name> | Slow English Story (<level>) with Subtitles`, at most 100 characters.
- `level`: `A2`, `B1` or `B2`.
- `summary`: one sentence.
- `description`: 2 short paragraphs. Paragraph one names the level and sets up the story without the ending. Paragraph two: "Listen, read the subtitles, learn the key words, and test yourself with the quiz at the end."
- `tags`: 8-10 search phrases learners use (for example "slow english", "english story", "B1 english").
- `thumbnail_text`: the story name, at most 4 words.
- `vocabulary`: 6-10 useful words from the story, each with a simple one-line `meaning` written at the story's level. Each word must appear in the story (an inflected form is fine).
- `paragraphs`: 8-12 paragraphs. Each has `text` and an `image_query`: 2-4 words describing a calm photo for that scene (for example "foggy harbour morning"). Photos must not need to show specific people's faces.
- `quiz`: 4-5 questions about the story, each with 3 `options` and the 0-based index of the correct `answer`. Vary which letter is correct.
