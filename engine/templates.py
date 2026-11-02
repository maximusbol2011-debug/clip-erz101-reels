"""Data-driven reel formats for the daily autopilot.

A spec is a dict (usually loaded from a JSON file in autopilot/specs/):
  {"slug": "...", "format": "list"|"mythfact"|"versus"|"stat",
   "palette": 0-5, "voice": "af_bella", "hook": "...", "items": [...], "cta": "...",
   "caption": "...", "hashtags": "..."}

Formats
  list      items: [{"title": "SHORT ON-SCREEN", "say": "spoken line"}]          numbered tips
  mythfact  items: [{"myth": "...", "fact": "..."}]                               red X / green check
  versus    items: [{"a": "...", "b": "...", "winner": "a"|"b", "why": "..."}]   A vs B split screen
  stat      items: [{"value": "70%", "label": "SHORT", "say": "spoken line"}]     big counter numbers

Every word shown on screen is also spoken, matching the existing engine.
"""
import math, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "reels-engine"))
from lib import *  # noqa

WHITE = (255, 255, 255)
GRN = (60, 220, 120)
RED = (255, 80, 90)

PALETTES = [  # bg top, bg bottom, glow, accent
    ((24, 18, 52), (6, 5, 16), (140, 90, 255), (255, 214, 10)),
    ((10, 34, 46), (4, 10, 16), (40, 170, 210), (255, 214, 10)),
    ((52, 14, 30), (12, 4, 10), (255, 70, 120), (255, 230, 120)),
    ((14, 40, 26), (4, 12, 8), (60, 220, 120), (255, 255, 255)),
    ((44, 30, 10), (12, 8, 4), (255, 160, 40), (255, 255, 255)),
    ((18, 18, 22), (4, 4, 6), (120, 120, 140), (0, 230, 255)),
]
CAP_STYLES = [
    dict(font="mont", size=92, wght=900, hi=(255, 214, 10)),
    dict(font="anton", size=104, wght=None, hi=(0, 230, 255), stroke=9),
    dict(font="mont", size=88, wght=900, box=(255, 60, 90), box_fg=(255, 255, 255)),
    dict(font="archivo", size=86, wght=None, hi=(60, 220, 120)),
]


def _bg(pal, seed):
    rng = random.Random(seed)
    dots = [(rng.randint(0, W), rng.randint(0, H), rng.random()) for _ in range(60)]
    base = gradient(pal[0], pal[1])

    def bg(img, d, t):
        img.paste(base)
        glow(img, 540 + 160 * math.sin(t * 0.4 + seed), 760, 520, pal[2], 0.28)
        for x, y, p in dots:
            yy = (y - t * 30 * (0.5 + p)) % H
            a = int(40 + 50 * p)
            d.ellipse([x - 3, yy - 3, x + 3, yy + 3], fill=(255, 255, 255, a))
    return bg


def _handle(d, t):
    text(d, (W / 2, 1800), "@clip.erz101", F("mont", 40, 700), (255, 255, 255, 150))


def _wrapped(img, s, font, cx, cy, t, start, fill, maxw=900, stroke=0):
    s = wrap(s, font, maxw)
    pop_text(img, s, font, cx, cy, t, start=start, fill=fill, stroke=stroke)


def _hook_scene(spec, pal, bg):
    hook = spec["hook"]
    def draw(img, d, t, dur, T):
        bg(img, d, T)
        q = eo(t / 0.5)
        rrect(d, (90, 560 - 40 * (1 - q), 990, 1000 - 40 * (1 - q)), 48, fill=(*pal[3], int(235 * q)))
        _wrapped(img, hook.upper(), F("anton", 110), W / 2, 780, t, 0.05, (16, 14, 22), maxw=800)
        _handle(d, t)
    return Scene(spec.get("hook_say", hook), draw, caps=False)


def _cta_scene(spec, pal, bg):
    cta = spec.get("cta", "Follow for more.")
    def draw(img, d, t, dur, T):
        bg(img, d, T)
        k = back(t / 0.5)
        rrect(d, (240, 700 - 10 * k, 840, 860), 60, fill=(*pal[3], 255))
        text(d, (540, 780), "FOLLOW", F("anton", 96), (16, 14, 22))
        pop_text(img, "@clip.erz101", F("mont", 64, 800), 540, 960, t, start=0.2, fill=WHITE)
        if t > 0.6:
            for i in range(3):
                a = (math.sin(t * 6 - i) + 1) / 2
                d.polygon([(540 - 30, 1080 + i * 40), (540 + 30, 1080 + i * 40), (540, 1110 + i * 40)], fill=(255, 255, 255, int(80 + 160 * a)))
    return Scene(cta, draw, cap_y=1300)


def _list_scenes(spec, pal, bg):
    out, n = [], len(spec["items"])
    for k, it in enumerate(spec["items"]):
        def draw(img, d, t, dur, T, k=k, it=it):
            bg(img, d, T)
            for j in range(n):  # progress dots
                c = pal[3] if j <= k else (255, 255, 255, 60)
                d.ellipse([540 - n * 30 + j * 60 - 12, 230, 540 - n * 30 + j * 60 + 12, 254], fill=c)
            s = back(t / 0.45)
            paste_layer(img, text_layer(str(k + 1), F("anton", 360), pal[3]), 540, 560, scale=0.6 + 0.4 * s)
            _wrapped(img, it["title"].upper(), F("anton", 96), W / 2, 880, t, 0.15, WHITE, maxw=860)
            _handle(d, t)
        out.append(Scene(it["say"], draw, cap_y=1320))
    return out


def _mythfact_scenes(spec, pal, bg):
    out = []
    for it in spec["items"]:
        def draw_m(img, d, t, dur, T, it=it):
            bg(img, d, T)
            pill(d, 540, 380, "MYTH", F("anton", 80), RED)
            _wrapped(img, it["myth"], F("mont", 76, 800), W / 2, 700, t, 0.1, WHITE, maxw=860)
            if t > dur * 0.55:
                q = eo((t - dur * 0.55) / 0.25)
                d.line([300, 560, 300 + 480 * q, 560 + 300 * q], fill=RED, width=22)
                d.line([780, 560, 780 - 480 * q, 560 + 300 * q], fill=RED, width=22)
            _handle(d, t)

        def draw_f(img, d, t, dur, T, it=it):
            bg(img, d, T)
            pill(d, 540, 380, "FACT", F("anton", 80), (30, 170, 90))
            _wrapped(img, it["fact"], F("mont", 76, 800), W / 2, 700, t, 0.1, WHITE, maxw=860)
            q = eo(t / 0.4)
            d.line([440, 960, 440 + 60 * q, 960 + 60 * q], fill=GRN, width=24)
            if q >= 1:
                q2 = eo((t - 0.4) / 0.3)
                d.line([500, 1020, 500 + 140 * q2, 1020 - 160 * q2], fill=GRN, width=24)
            _handle(d, t)
        out += [Scene("Myth. " + it["myth"], draw_m, cap_y=1320), Scene("Fact. " + it["fact"], draw_f, cap_y=1320)]
    return out


def _versus_scenes(spec, pal, bg):
    out = []
    for it in spec["items"]:
        def draw(img, d, t, dur, T, it=it, reveal=False):
            bg(img, d, T)
            win = it.get("winner", "a")
            for side, label, x0 in (("a", it["a"], 60), ("b", it["b"], 560)):
                q = eo(t / 0.4)
                lit = reveal and t > 0.3
                col = (*GRN, 230) if lit and side == win else ((60, 60, 70, 200) if lit else (255, 255, 255, 30))
                rrect(d, (x0, 420 + 60 * (1 - q), x0 + 460, 1000), 40, fill=col)
                text(d, (x0 + 230, 500), side.upper(), F("anton", 110), pal[3] if not lit else WHITE)
                tl = text_layer(wrap(label.upper(), F("anton", 64), 400), F("anton", 64), WHITE, spacing=4)
                paste_layer(img, tl, x0 + 230, 760, alpha=q)
            if not reveal:
                pop_text(img, "VS", F("anton", 120), 540, 1080, t, 0.3, fill=pal[3], stroke=8)
            _handle(d, t)
        say_q = f"{it['a']}, or {it['b']}?"
        out.append(Scene(say_q, draw, cap_y=1300))
        out.append(Scene(f"{it[it.get('winner', 'a')]} wins. {it.get('why', '')}".strip(),
                         lambda img, d, t, dur, T, f=draw: f(img, d, t, dur, T, reveal=True), cap_y=1300))
    return out


def _stat_scenes(spec, pal, bg):
    out = []
    for it in spec["items"]:
        m = re.match(r"^(\D*)([\d.,]+)(.*)$", it["value"])
        def draw(img, d, t, dur, T, it=it, m=m):
            bg(img, d, T)
            if m:
                num = float(m.group(2).replace(",", ""))
                cur = num * eo(t / 1.0)
                s = m.group(1) + (f"{cur:,.0f}" if num >= 10 or num == int(num) else f"{cur:.1f}") + m.group(3)
            else:
                s = it["value"]
            text(d, (540, 640), s, F("anton", 260), pal[3])
            _wrapped(img, it["label"].upper(), F("anton", 88), W / 2, 900, t, 0.2, WHITE, maxw=860)
            _handle(d, t)
        out.append(Scene(it["say"], draw, cap_y=1320))
    return out


BUILDERS = dict(list=_list_scenes, mythfact=_mythfact_scenes, versus=_versus_scenes, stat=_stat_scenes)


def make(spec):
    seed = sum(map(ord, spec["slug"]))
    pal = PALETTES[spec.get("palette", seed % len(PALETTES)) % len(PALETTES)]
    bg = _bg(pal, seed)
    scenes = [_hook_scene(spec, pal, bg)] + BUILDERS[spec["format"]](spec, pal, bg) + [_cta_scene(spec, pal, bg)]
    cs = dict(CAP_STYLES[spec.get("cap_style", seed % len(CAP_STYLES)) % len(CAP_STYLES)])
    return Video(spec["slug"], scenes, voice=spec.get("voice", "af_bella"), speed=spec.get("speed", 1.06), cap_style=cs)
