"""Backgrounds, slides and thumbnails, drawn with Pillow."""
from __future__ import annotations

import hashlib
import io
import os
import random
import re
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .story import word_matches

FONT_CANDIDATES = {
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
}

WHITE = (255, 255, 255)
SOFT = (222, 226, 232)
PANEL = (12, 16, 24)
LEVEL_NAMES = {"A2": "Elementary", "B1": "Intermediate", "B2": "Upper intermediate"}


def font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES[weight]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


# ---------- backgrounds ----------

def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def generated_background(seed: str, size: tuple[int, int]) -> Image.Image:
    """A soft two-colour gradient with blurred shapes, deterministic per seed."""
    rnd = random.Random(seed)
    w, h = size
    hue_a = [rnd.randint(20, 90) for _ in range(3)]
    hue_b = [min(255, c + rnd.randint(30, 90)) for c in hue_a]
    small = Image.new("RGB", (64, 36))
    px = small.load()
    for y in range(36):
        for x in range(64):
            t = (x / 63 + y / 35) / 2
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(hue_a, hue_b))
    img = small.resize(size, Image.BICUBIC)
    shapes = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shapes)
    for _ in range(6):
        r = rnd.randint(h // 6, h // 2)
        cx, cy = rnd.randint(0, w), rnd.randint(0, h)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, rnd.randint(12, 35)))
    shapes = shapes.filter(ImageFilter.GaussianBlur(60))
    return Image.alpha_composite(img.convert("RGBA"), shapes).convert("RGB")


class Backgrounds:
    """Finds a background per image query: a Pexels photo, or a generated gradient."""

    def __init__(self, size: tuple[int, int], cache_dir: Path, source: str = "pexels"):
        self.size = size
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = os.environ.get("PEXELS_API_KEY", "")
        self.use_pexels = source == "pexels" and bool(self.api_key)
        self.credits: list[str] = []

    def get(self, query: str, seed: str) -> Image.Image:
        if self.use_pexels and query:
            try:
                return self._pexels(query, seed)
            except Exception as exc:  # a missing photo should never stop a render
                print(f"  pexels: no photo for '{query}' ({exc}); using a generated background")
        return generated_background(seed + query, self.size)

    def _pexels(self, query: str, seed: str) -> Image.Image:
        key = hashlib.sha1(f"{query}|{seed}".encode()).hexdigest()[:16]
        path = self.cache_dir / f"{key}.jpg"
        if not path.exists():
            r = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "orientation": "landscape", "per_page": 15},
                headers={"Authorization": self.api_key},
                timeout=30,
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if not photos:
                raise LookupError("no results")
            photo = photos[int(key, 16) % len(photos)]
            img = requests.get(photo["src"]["original"], params={"auto": "compress", "w": 2400}, timeout=60)
            img.raise_for_status()
            path.write_bytes(img.content)
            path.with_suffix(".txt").write_text(f"{photo['photographer']} ({photo['url']})")
        credit = path.with_suffix(".txt")
        if credit.exists() and credit.read_text() not in self.credits:
            self.credits.append(credit.read_text())
        return cover(Image.open(path).convert("RGB"), self.size)


def dim(img: Image.Image, amount: float = 0.45, blur: float = 2.0) -> Image.Image:
    img = img.filter(ImageFilter.GaussianBlur(blur)) if blur else img.copy()
    return Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), amount)


# ---------- text layout ----------

def _norm(token: str) -> str:
    return re.sub(r"[^a-z']", "", token.lower())


def highlight_mask(tokens: list[str], phrases: list[str]) -> list[bool]:
    norm = [_norm(t) for t in tokens]
    mask = [False] * len(tokens)
    for phrase in phrases:
        parts = [_norm(p) for p in phrase.split() if _norm(p)]
        if not parts:
            continue
        for i in range(len(norm) - len(parts) + 1):
            window = norm[i:i + len(parts)]
            if window[:-1] == parts[:-1] and word_matches(window[-1], parts[-1]):
                for j in range(i, i + len(parts)):
                    mask[j] = True
    return mask


def wrap_tokens(tokens: list[str], fnt, max_width: int, draw: ImageDraw.ImageDraw) -> list[list[int]]:
    lines, current, width = [], [], 0
    space = draw.textlength(" ", font=fnt)
    for i, tok in enumerate(tokens):
        w = draw.textlength(tok, font=fnt)
        if current and width + space + w > max_width:
            lines.append(current)
            current, width = [], 0
        width += (space if current else 0) + w
        current.append(i)
    if current:
        lines.append(current)
    return lines


def draw_rich_text(img, text, box, size, accent, phrases=(), weight="regular", align="center", color=WHITE):
    """Draw wrapped text in box (x, y, w, h), vertically centred; matching phrases in accent bold."""
    draw = ImageDraw.Draw(img)
    x0, y0, bw, bh = box
    tokens = text.split()
    mask = highlight_mask(tokens, list(phrases))
    while True:
        reg, bold = font(size, weight), font(size, "bold")
        lines = wrap_tokens(tokens, bold, bw, draw)
        line_h = int(size * 1.35)
        if len(lines) * line_h <= bh or size <= 28:
            break
        size -= 4
    total_h = len(lines) * line_h
    y = y0 + (bh - total_h) // 2
    space = draw.textlength(" ", font=reg)
    for line in lines:
        widths = [draw.textlength(tokens[i], font=bold if mask[i] else reg) for i in line]
        line_w = sum(widths) + space * (len(line) - 1)
        x = x0 + (bw - line_w) / 2 if align == "center" else x0
        for i, w in zip(line, widths):
            draw.text((x, y), tokens[i], font=bold if mask[i] else reg, fill=accent if mask[i] else color)
            x += w + space
        y += line_h
    return y


def rounded_panel(img, box, radius=36, fill=PANEL, alpha=200):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(box, radius=radius, fill=fill + (alpha,))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def badge(img, xy, text, accent, size=34):
    draw = ImageDraw.Draw(img)
    f = font(size, "bold")
    w = draw.textlength(text, font=f)
    x, y = xy
    draw.rounded_rectangle((x, y, x + w + size * 1.2, y + size * 1.8), radius=size, fill=accent)
    draw.text((x + size * 0.6, y + size * 0.38), text, font=f, fill=(20, 20, 20))
    return x + w + size * 1.2


# ---------- slides ----------

class SlideMaker:
    def __init__(self, size, accent: str, out_dir: Path):
        self.size = size
        self.w, self.h = size
        self.accent = hex_rgb(accent)
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.count = 0

    def save(self, img: Image.Image) -> Path:
        self.count += 1
        path = self.out_dir / f"{self.count:04d}.png"
        img.save(path, optimize=False, compress_level=1)
        return path

    def header(self, img, label: str):
        draw = ImageDraw.Draw(img)
        draw.text((64, 48), label, font=font(30, "bold"), fill=SOFT)

    def progress(self, img, fraction: float):
        draw = ImageDraw.Draw(img)
        y = self.h - 14
        draw.rectangle((0, y, self.w, self.h), fill=(40, 44, 52))
        draw.rectangle((0, y, int(self.w * fraction), self.h), fill=self.accent)

    def title(self, bg, title: str, level: str, subtitle: str) -> Path:
        img = dim(bg, 0.55)
        draw = ImageDraw.Draw(img)
        label = f"{level}  ·  {LEVEL_NAMES.get(level, '')}"
        f = font(36, "bold")
        lw = draw.textlength(label, font=f) + 43
        badge(img, ((self.w - lw) // 2, int(self.h * 0.24)), label, self.accent, 36)
        draw_rich_text(img, title, (160, int(self.h * 0.34), self.w - 320, int(self.h * 0.34)), 104, self.accent, weight="bold")
        draw_rich_text(img, subtitle, (160, int(self.h * 0.70), self.w - 320, 80), 40, self.accent, color=SOFT)
        return self.save(img)

    def sentence(self, bg, sentence: str, phrases, label: str, fraction: float) -> Path:
        img = dim(bg, 0.35, blur=0)
        top = int(self.h * 0.52)
        img = rounded_panel(img, (110, top, self.w - 110, self.h - 70), alpha=205)
        draw_rich_text(img, sentence, (170, top + 30, self.w - 340, self.h - 70 - top - 60), 64, self.accent, phrases)
        self.header(img, label)
        self.progress(img, fraction)
        return self.save(img)

    def vocab(self, bg, word: str, meaning: str, index: int, total: int) -> Path:
        img = rounded_panel(dim(bg, 0.6), (240, 200, self.w - 240, self.h - 200), alpha=215)
        draw = ImageDraw.Draw(img)
        draw.text((300, 250), f"KEY WORDS  {index}/{total}", font=font(30, "bold"), fill=SOFT)
        draw_rich_text(img, word, (300, 330, self.w - 600, 170), 120, self.accent, color=self.accent, weight="bold")
        draw_rich_text(img, meaning, (300, 520, self.w - 600, 300), 56, self.accent)
        return self.save(img)

    def quiz(self, bg, number: int, total: int, question: str, options: list[str], answer: int | None) -> Path:
        img = rounded_panel(dim(bg, 0.6), (200, 120, self.w - 200, self.h - 120), alpha=215)
        draw = ImageDraw.Draw(img)
        draw.text((260, 165), f"QUIZ  ·  QUESTION {number} OF {total}", font=font(30, "bold"), fill=SOFT)
        y = draw_rich_text(img, question, (260, 220, self.w - 520, 220), 60, self.accent, weight="bold", align="left")
        y = max(y + 30, 470)
        for i, opt in enumerate(options):
            correct = answer is not None and i == answer
            letter = "ABCDEF"[i]
            box = (260, y, self.w - 260, y + 92)
            if correct:
                draw.rounded_rectangle(box, radius=24, fill=self.accent)
            else:
                draw.rounded_rectangle(box, radius=24, outline=(120, 126, 140), width=3)
            color = (20, 20, 20) if correct else WHITE
            draw.text((300, y + 20), f"{letter}.", font=font(44, "bold"), fill=color)
            draw.text((380, y + 20), opt, font=font(44), fill=color)
            y += 112
        if answer is None:
            draw.text((260, self.h - 190), "Pause the video if you need more time.", font=font(30), fill=SOFT)
        return self.save(img)

    def outro(self, bg, lines: list[str]) -> Path:
        img = dim(bg, 0.6)
        draw_rich_text(img, lines[0], (160, int(self.h * 0.28), self.w - 320, 200), 96, self.accent, weight="bold")
        draw_rich_text(img, lines[1], (160, int(self.h * 0.52), self.w - 320, 200), 48, self.accent, color=SOFT)
        return self.save(img)


def thumbnail(bg: Image.Image, text: str, level: str, accent: str, path: Path) -> Path:
    size = (1280, 720)
    img = cover(bg, size)
    shade = Image.new("L", size)
    sd = ImageDraw.Draw(shade)
    for x in range(size[0]):
        sd.line([(x, 0), (x, size[1])], fill=int(max(0, 215 - x * 0.22)))
    img = Image.composite(Image.new("RGB", size, (0, 0, 0)), img, shade)
    acc = hex_rgb(accent)
    draw = ImageDraw.Draw(img)
    draw.text((60, 52), "SLOW ENGLISH", font=font(44, "bold"), fill=acc)
    draw_rich_text(img, text.upper(), (60, 140, 760, 420), 104, acc, weight="bold", align="left")
    f = font(120, "bold")
    w = draw.textlength(level, font=f)
    draw.rounded_rectangle((size[0] - w - 120, size[1] - 210, size[0] - 50, size[1] - 50), radius=36, fill=acc)
    draw.text((size[0] - w - 85, size[1] - 203), level, font=f, fill=(20, 20, 20))
    img.save(path, quality=90)
    return path


def image_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
