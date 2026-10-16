"""Story items: the JSON files the writing task drops into a channel's queue."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

LEVELS = ("A2", "B1", "B2")
_SENTENCE_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"'”’)]))\s+(?=[\"'“‘(]?[A-Z0-9])")
_WORD = re.compile(r"[A-Za-z']+")


class StoryError(ValueError):
    """The story file is malformed and cannot be rendered."""


@dataclass
class Paragraph:
    text: str
    image_query: str = ""

    @property
    def sentences(self) -> list[str]:
        return split_sentences(self.text)


@dataclass
class QuizQuestion:
    question: str
    options: list[str]
    answer: int


@dataclass
class Story:
    path: Path
    slug: str
    title: str
    level: str
    summary: str
    description: str
    tags: list[str]
    thumbnail_text: str
    vocabulary: list[dict]
    paragraphs: list[Paragraph]
    quiz: list[QuizQuestion]
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs)

    @property
    def sentences(self) -> list[str]:
        return [s for p in self.paragraphs for s in p.sentences]

    @property
    def word_count(self) -> int:
        return len(words(self.text))

    @property
    def avg_sentence_words(self) -> float:
        sents = self.sentences
        return self.word_count / len(sents) if sents else 0.0


def split_sentences(text: str) -> list[str]:
    text = " ".join(text.split())
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def word_matches(token: str, base: str) -> bool:
    """True if token is base or a simple inflection of it: walk/walked, rescue/rescuing, city/cities."""
    stem = base[:-1] if len(base) > 3 and base[-1] in "ey" else base
    return token.startswith(stem) and len(token) - len(stem) <= 4


def contains_phrase(text: str, phrase: str) -> bool:
    toks, parts = words(text), words(phrase)
    if not parts:
        return False
    n = len(parts)
    for i in range(len(toks) - n + 1):
        if toks[i:i + n - 1] == parts[:-1] and word_matches(toks[i + n - 1], parts[-1]):
            return True
    return False


def _require(data: dict, key: str, kind: type, path: Path):
    if key not in data:
        raise StoryError(f"{path.name}: missing field '{key}'")
    if not isinstance(data[key], kind):
        raise StoryError(f"{path.name}: field '{key}' must be {kind.__name__}")
    return data[key]


def load_story(path: Path) -> Story:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoryError(f"{Path(path).name}: invalid JSON ({exc})") from exc
    path = Path(path)

    level = _require(data, "level", str, path)
    if level not in LEVELS:
        raise StoryError(f"{path.name}: level must be one of {', '.join(LEVELS)}")

    paragraphs = []
    for i, p in enumerate(_require(data, "paragraphs", list, path)):
        if not isinstance(p, dict) or not p.get("text", "").strip():
            raise StoryError(f"{path.name}: paragraph {i + 1} needs a 'text'")
        paragraphs.append(Paragraph(text=p["text"].strip(), image_query=p.get("image_query", "")))
    if not paragraphs:
        raise StoryError(f"{path.name}: no paragraphs")

    quiz = []
    for i, q in enumerate(_require(data, "quiz", list, path)):
        opts = q.get("options", [])
        ans = q.get("answer")
        if not q.get("question") or len(opts) < 2 or not isinstance(ans, int) or not 0 <= ans < len(opts):
            raise StoryError(f"{path.name}: quiz question {i + 1} needs a question, 2+ options and a valid answer index")
        quiz.append(QuizQuestion(question=q["question"], options=list(opts), answer=ans))

    vocab = _require(data, "vocabulary", list, path)
    for i, v in enumerate(vocab):
        if not isinstance(v, dict) or not v.get("word") or not v.get("meaning"):
            raise StoryError(f"{path.name}: vocabulary item {i + 1} needs 'word' and 'meaning'")

    title = _require(data, "title", str, path).strip()
    if not 10 <= len(title) <= 100:
        raise StoryError(f"{path.name}: title must be 10-100 characters (YouTube limit is 100)")
    if "<" in title or ">" in title:
        raise StoryError(f"{path.name}: title may not contain < or >")

    tags = [str(t) for t in data.get("tags", [])]
    if sum(len(t) for t in tags) > 450:
        raise StoryError(f"{path.name}: tags are too long in total (YouTube limit is 500 characters)")

    return Story(
        path=path,
        slug=_require(data, "slug", str, path),
        title=title,
        level=level,
        summary=data.get("summary", ""),
        description=_require(data, "description", str, path),
        tags=tags,
        thumbnail_text=data.get("thumbnail_text") or title.split("|")[0].strip(),
        vocabulary=vocab,
        paragraphs=paragraphs,
        quiz=quiz,
        raw=data,
    )
