"""Tiny motion-graphics engine: narrated scenes, word-synced captions, ffmpeg output."""
import hashlib, math, os, re, subprocess, json
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS, SR = 1080, 1920, 30, 24000
CACHE = os.environ.get("TTS_CACHE", "/tmp/ttscache")
os.makedirs(CACHE, exist_ok=True)

FONT_FILES = {
    "mont": "/opt/fonts/Montserrat.ttf",
    "anton": "/opt/fonts/Anton-Regular.ttf",
    "bebas": "/opt/fonts/BebasNeue-Regular.ttf",
    "archivo": "/opt/fonts/ArchivoBlack-Regular.ttf",
    "caveat": "/opt/fonts/Caveat.ttf",
    "inter": "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
    "interxb": "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "serif": "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "mono": "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-ExtraBold.ttf",
}
_fonts = {}


def F(name, size, wght=None):
    key = (name, int(size), wght)
    if key not in _fonts:
        f = ImageFont.truetype(FONT_FILES[name], int(size))
        if wght:
            f.set_variation_by_axes([wght])
        _fonts[key] = f
    return _fonts[key]


# ---------- easing ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, a, b):
    return clamp((t - a) / (b - a)) if b > a else float(t >= a)


def eo(x):  # ease out cubic
    x = clamp(x)
    return 1 - (1 - x) ** 3


def eio(x):
    x = clamp(x)
    return 3 * x * x - 2 * x * x * x


def back(x, s=1.70158):  # ease out back (overshoot)
    x = clamp(x) - 1
    return x * x * ((s + 1) * x + s) + 1


def lerp(a, b, x):
    return a + (b - a) * x


def lerpc(c1, c2, x):
    return tuple(int(lerp(a, b, x)) for a, b in zip(c1, c2))


def hexc(h, a=None):
    h = h.lstrip("#")
    c = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return c + (a,) if a is not None else c


# ---------- drawing helpers ----------
_bgcache = {}


def gradient(c1, c2, vertical=True, size=(W, H)):
    key = (c1, c2, vertical, size)
    if key not in _bgcache:
        w, h = size
        n = h if vertical else w
        ramp = np.linspace(0, 1, n)[:, None]
        cols = (np.array(c1)[None, :] * (1 - ramp) + np.array(c2)[None, :] * ramp).astype(np.uint8)
        if vertical:
            arr = np.repeat(cols[:, None, :], w, axis=1)
        else:
            arr = np.repeat(cols[None, :, :], h, axis=0)
        # subtle film grain baked in so flat gradients don't band
        rng = np.random.default_rng(7)
        arr = np.clip(arr.astype(np.int16) + rng.integers(-3, 4, arr.shape), 0, 255).astype(np.uint8)
        _bgcache[key] = Image.fromarray(arr, "RGB")
    return _bgcache[key].copy()


_glows = {}


def glow(img, cx, cy, r, color, strength=0.55):
    key = (int(r), color, strength)
    if key not in _glows:
        s = int(r * 2)
        yy, xx = np.mgrid[0:s, 0:s]
        d = np.sqrt((xx - r) ** 2 + (yy - r) ** 2) / r
        a = np.clip(1 - d, 0, 1) ** 2 * 255 * strength
        rgba = np.zeros((s, s, 4), np.uint8)
        rgba[..., :3] = color
        rgba[..., 3] = a.astype(np.uint8)
        _glows[key] = Image.fromarray(rgba, "RGBA")
    g = _glows[key]
    img.paste(g, (int(cx - r), int(cy - r)), g)


def text(d, xy, s, font, fill=(255, 255, 255), anchor="mm", stroke=0, sfill=(0, 0, 0), spacing=10, align="center"):
    if "\n" in s:
        d.multiline_text(xy, s, font=font, fill=fill, anchor=anchor, stroke_width=stroke,
                         stroke_fill=sfill, spacing=spacing, align=align)
    else:
        d.text(xy, s, font=font, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sfill)


def tw(s, font, stroke=0):
    b = font.getbbox(s, stroke_width=stroke)
    return b[2] - b[0]


def wrap(s, font, maxw):
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if tw(trial, font) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return "\n".join(lines)


_layers = {}


def text_layer(s, font, fill=(255, 255, 255), stroke=0, sfill=(0, 0, 0), spacing=10):
    key = (s, id(font), fill, stroke, sfill, spacing)
    if key not in _layers:
        dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        b = [int(math.floor(v)) if i < 2 else int(math.ceil(v)) for i, v in
             enumerate(dummy.multiline_textbbox((0, 0), s, font=font, stroke_width=stroke, spacing=spacing, align="center"))]
        pad = 8
        im = Image.new("RGBA", (b[2] - b[0] + pad * 2, b[3] - b[1] + pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(im).multiline_text((pad - b[0], pad - b[1]), s, font=font, fill=fill, stroke_width=stroke,
                                          stroke_fill=sfill, spacing=spacing, align="center")
        _layers[key] = im
    return _layers[key]


def paste_layer(img, layer, cx, cy, scale=1.0, alpha=1.0, rot=0.0):
    if scale <= 0.01 or alpha <= 0.01:
        return
    L = layer
    if abs(scale - 1) > 0.005:
        L = L.resize((max(1, int(L.width * scale)), max(1, int(L.height * scale))), Image.BILINEAR)
    if rot:
        L = L.rotate(rot, resample=Image.BICUBIC, expand=True)
    if alpha < 0.999:
        L = L.copy()
        L.putalpha(L.getchannel("A").point(lambda v: int(v * alpha)))
    img.paste(L, (int(cx - L.width / 2), int(cy - L.height / 2)), L)


def pop_text(img, s, font, cx, cy, t, start=0.0, fill=(255, 255, 255), stroke=0, sfill=(0, 0, 0), dur=0.35, rot=0.0):
    if t < start:
        return
    x = (t - start) / dur
    paste_layer(img, text_layer(s, font, fill, stroke, sfill), cx, cy, scale=back(x) if x < 1 else 1.0,
                alpha=clamp(x * 3), rot=rot)


def rrect(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle([int(v) for v in box], radius=int(r), fill=fill, outline=outline, width=width)


def pill(d, cx, cy, s, font, bg, fg=(255, 255, 255), padx=34, pady=18):
    w = tw(s, font)
    b = font.getbbox("Ag")
    h = b[3] - b[1]
    rrect(d, (cx - w / 2 - padx, cy - h / 2 - pady, cx + w / 2 + padx, cy + h / 2 + pady), h / 2 + pady, fill=bg)
    text(d, (cx, cy), s, font, fg)


def shadow_box(img, box, r, blur=30, alpha=120):
    x0, y0, x1, y1 = [int(v) for v in box]
    pad = blur * 2
    sh = Image.new("L", (x1 - x0 + pad * 2, y1 - y0 + pad * 2), 0)
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 14, pad + x1 - x0, pad + y1 - y0 + 14], r, fill=alpha)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    img.paste((0, 0, 0), (x0 - pad, y0 - pad), sh)


# ---------- reusable illustrations ----------
def speaker(d, cx, cy, s, color, facing=1, talk=0.0, headphone=(30, 30, 36)):
    """Simple podcast guest silhouette, head centre (cx, cy), head radius s."""
    sh = (cx - s * 2.1, cy + s * 1.05, cx + s * 2.1, cy + s * 4.6)
    d.pieslice([sh[0], sh[1], sh[2], sh[3] + s * 2.4], 180, 360, fill=color)
    d.rectangle([cx - s * 0.45, cy + s * 0.6, cx + s * 0.45, cy + s * 1.4], fill=color)
    d.ellipse([cx - s, cy - s * 1.1, cx + s, cy + s], fill=color)
    d.arc([cx - s * 1.1, cy - s * 1.25, cx + s * 1.1, cy + s * 0.9], 190, 350, fill=headphone, width=int(s * 0.22))
    d.ellipse([cx - s * 1.2, cy - s * 0.3, cx - s * 0.8, cy + s * 0.35], fill=headphone)
    d.ellipse([cx + s * 0.8, cy - s * 0.3, cx + s * 1.2, cy + s * 0.35], fill=headphone)
    # mic on boom arm
    mx = cx + facing * s * 1.55
    my = cy + s * 0.55
    d.line([mx + facing * s * 0.4, my + s * 0.2, mx + facing * s * 1.6, my + s * 2.3], fill=(60, 60, 70), width=int(s * 0.14))
    rrect(d, (mx - s * 0.32, my - s * 0.55, mx + s * 0.32, my + s * 0.55), s * 0.3, fill=(45, 45, 52))
    if talk > 0:  # little speech ticks
        for k in range(3):
            a = math.radians(-30 + k * 30)
            r0, r1 = s * 2.6, s * (2.6 + 0.5 * talk)
            ox = cx + facing * s * 0.2
            d.line([ox + facing * math.cos(a) * r0, cy - s * 1.6 + math.sin(a) * r0 * 0.4,
                    ox + facing * math.cos(a) * r1, cy - s * 1.6 + math.sin(a) * r1 * 0.4],
                   fill=(255, 255, 255, int(200 * talk)), width=6)


def podcast_scene(box, t, zoom=1.0, focus=0.5, bg1=(38, 30, 60), bg2=(18, 16, 28), warm=(255, 150, 80),
                  c1=(232, 120, 90), c2=(90, 150, 230), talk_who=None):
    """Return an RGB image of a stylised two-person podcast set, sized to box."""
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    # render a wide master shot then crop/zoom into it
    MW, MH = 1600, 900
    key = ("pod", bg1, bg2, warm, c1, c2)
    if key not in _bgcache:
        m = gradient(bg1, bg2, True, (MW, MH))
        glow(m, 300, 260, 260, warm, 0.35)
        glow(m, 1300, 220, 240, (120, 160, 255), 0.3)
        md = ImageDraw.Draw(m, "RGBA")
        for i in range(9):  # acoustic panels
            px = 80 + i * 170
            rrect(md, (px, 120, px + 130, 330), 10, fill=(255, 255, 255, 10))
        md.rectangle([0, 700, MW, MH], fill=(14, 12, 20))
        md.ellipse([560, 600, 1040, 760], fill=(28, 24, 36))
        _bgcache[key] = m
    m = _bgcache[key].copy()
    md = ImageDraw.Draw(m, "RGBA")
    bob = math.sin(t * 2.3) * 4
    speaker(md, 520, 400 + bob, 92, c1, facing=1, talk=(0.5 + 0.5 * math.sin(t * 9)) if talk_who == 0 else 0)
    speaker(md, 1080, 405 - bob, 92, c2, facing=-1, talk=(0.5 + 0.5 * math.sin(t * 9)) if talk_who == 1 else 0)
    # crop window: aspect of output, centred on focus x, scaled by zoom
    ar = w / h
    ch = MH / zoom
    cw = ch * ar
    if cw > MW:
        cw = MW / zoom
        ch = cw / ar
    cx = clamp(lerp(cw / 2, MW - cw / 2, focus), cw / 2, MW - cw / 2)
    cy = MH / 2 + (MH - ch) * 0.05
    crop = m.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2)))
    return crop.resize((w, h), Image.BILINEAR)


def face(d, cx, cy, r, mood, color=(255, 205, 60)):
    """Emoji-style face. mood 0=meh, 1=smile, 2=impressed, 3=shocked."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    ey = cy - r * 0.18
    eh = r * (0.16 + 0.07 * mood)
    for sx in (-1, 1):
        ex = cx + sx * r * 0.36
        d.ellipse([ex - r * 0.1, ey - eh, ex + r * 0.1, ey + eh], fill=(40, 30, 20))
        lift = r * (0.05 + 0.1 * mood)
        d.line([ex - sx * r * 0.16, ey - eh - lift - r * 0.1, ex + sx * r * 0.16, ey - eh - lift * 0.7 - r * 0.08],
               fill=(40, 30, 20), width=int(r * 0.07))
    my = cy + r * 0.42
    if mood == 0:
        d.line([cx - r * 0.3, my, cx + r * 0.3, my], fill=(40, 30, 20), width=int(r * 0.08))
    elif mood == 1:
        d.arc([cx - r * 0.38, my - r * 0.3, cx + r * 0.38, my + r * 0.12], 20, 160, fill=(40, 30, 20), width=int(r * 0.08))
    elif mood == 2:
        d.ellipse([cx - r * 0.13, my - r * 0.12, cx + r * 0.13, my + r * 0.16], fill=(40, 30, 20))
    else:
        d.ellipse([cx - r * 0.22, my - r * 0.18, cx + r * 0.22, my + r * 0.32], fill=(40, 30, 20))
        d.ellipse([cx - r * 0.13, my + r * 0.05, cx + r * 0.13, my + r * 0.28], fill=(220, 80, 90))


def ghost(d, cx, cy, s, t, color=(245, 245, 250)):
    pts = []
    for a in np.linspace(math.pi, 2 * math.pi, 30):
        pts.append((cx + math.cos(a) * s, cy - s * 0.2 + math.sin(a) * s))
    bottom = cy + s * 1.6
    pts.append((cx + s, bottom))
    n = 5
    for i in range(n * 8 + 1):
        x = cx + s - i * (2 * s) / (n * 8)
        y = bottom + math.sin(i / 8 * 2 * math.pi + t * 5) * s * 0.09
        pts.append((x, y))
    pts.append((cx - s, cy - s * 0.2))
    d.polygon(pts, fill=color)
    blink = 0.15 if (t % 3.2) < 0.12 else 1
    for sx in (-1, 1):
        ex = cx + sx * s * 0.35
        d.ellipse([ex - s * 0.13, cy - s * 0.42 - s * 0.2 * blink, ex + s * 0.13, cy - s * 0.42 + s * 0.2 * blink], fill=(20, 18, 30))
    d.ellipse([cx - s * 0.12, cy + s * 0.02, cx + s * 0.12, cy + s * 0.3], fill=(20, 18, 30))


def phone(img, d, box, r=70, bezel=(16, 16, 20), screen=(250, 250, 252)):
    x0, y0, x1, y1 = box
    shadow_box(img, box, r)
    rrect(d, box, r, fill=bezel)
    rrect(d, (x0 + 16, y0 + 16, x1 - 16, y1 - 16), r - 14, fill=screen)
    rrect(d, ((x0 + x1) / 2 - 70, y0 + 34, (x0 + x1) / 2 + 70, y0 + 72), 20, fill=bezel)
    return (x0 + 16, y0 + 16, x1 - 16, y1 - 16)


def fmt_int(n):
    return f"{int(n):,}"


# ---------- TTS ----------
_kokoro = None


def synth(text_, voice, speed):
    global _kokoro
    h = hashlib.md5(f"{voice}|{speed}|{text_}".encode()).hexdigest()
    p = f"{CACHE}/{h}.npy"
    if os.path.exists(p):
        return np.load(p)
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro("/opt/kokoro/kokoro-v1.0.onnx", "/opt/kokoro/voices-v1.0.bin")
    a, sr = _kokoro.create(text_, voice=voice, speed=speed, lang="en-us")
    assert sr == SR
    a = a.astype(np.float32)
    # trim leading/trailing silence
    env = np.abs(a) > 0.01
    idx = np.where(env)[0]
    if len(idx):
        a = a[max(0, idx[0] - 240): idx[-1] + 1200]
    np.save(p, a)
    return a


def split_sentences(s):
    parts = re.split(r"(?<=[.!?])\s+", s.strip())
    return [p for p in parts if p]


def syll(w):
    w = re.sub(r"[^a-z0-9]", "", w.lower())
    if not w:
        return 1
    if w.isdigit():
        return 2 * len(w)
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def word_times(sentence, dur):
    """Estimate word timings inside one synthesized sentence."""
    words = sentence.split()
    wts = []
    for w in words:
        wt = 0.6 + syll(w) * 1.0 + len(re.sub(r"\W", "", w)) * 0.08
        if re.search(r"[,;:]$", w):
            wt += 1.6
        elif re.search(r"[.!?]$", w):
            wt += 0.8
        wts.append(wt)
    tot = sum(wts)
    out, acc = [], 0.0
    for w, wt in zip(words, wts):
        out.append((w, acc / tot * dur, (acc + wt) / tot * dur))
        acc += wt
    return out


# ---------- video model ----------
class Scene:
    def __init__(self, say, draw, caps=True, pad=0.3, min_dur=0.0, cap_y=None, voice=None):
        self.say, self.draw, self.caps, self.pad, self.min_dur, self.cap_y, self.voice = say, draw, caps, pad, min_dur, cap_y, voice


class Video:
    def __init__(self, slug, scenes, voice="am_michael", speed=1.08, cap_y=1240, cap_style=None, overlay=None):
        self.slug, self.scenes, self.voice, self.speed, self.cap_y = slug, scenes, voice, speed, cap_y
        self.cap_style = cap_style or {}
        self.overlay = overlay

    def build_audio(self):
        chunks, t = [], 0.0
        self.words = []
        lead = 0.08
        for i, sc in enumerate(self.scenes):
            sc.start = t
            st = t + lead
            for j, sent in enumerate(split_sentences(sc.say)):
                a = synth(sent, sc.voice or self.voice, self.speed)
                d = len(a) / SR
                for w, a0, a1 in word_times(sent, d):
                    self.words.append(dict(w=w, s=st + a0, e=st + a1, scene=i))
                chunks.append((st, a))
                st += d + 0.16
            st -= 0.16
            sc.audio_end = st - sc.start
            sc.dur = max(st - t + sc.pad, sc.min_dur)
            t += sc.dur
            lead = 0.0
        self.scenes[-1].dur += 0.5
        self.total = sum(s.dur for s in self.scenes)
        buf = np.zeros(int((self.total + 0.2) * SR), np.float32)
        for st, a in chunks:
            k = int(st * SR)
            buf[k:k + len(a)] += a
        self.audio = buf
        self._groups()

    def _groups(self):
        maxw = self.cap_style.get("max_words", 3)
        maxc = self.cap_style.get("max_chars", 18)
        self.groups = []
        cur = []
        for k, w in enumerate(self.words):
            if cur and (cur[0]["scene"] != w["scene"] or len(cur) >= maxw or
                        sum(len(x["w"]) + 1 for x in cur) + len(w["w"]) > maxc):
                self.groups.append(cur)
                cur = []
            cur.append(w)
            if re.search(r"[.!?,;:]$", w["w"]):
                self.groups.append(cur)
                cur = []
        if cur:
            self.groups.append(cur)
        for gi, g in enumerate(self.groups):
            g_end = g[-1]["e"] + 0.25
            if gi + 1 < len(self.groups):
                nxt = self.groups[gi + 1]
                if nxt[0]["scene"] == g[0]["scene"]:
                    g_end = nxt[0]["s"]
                else:
                    sc = self.scenes[g[0]["scene"]]
                    g_end = sc.start + sc.dur
            else:
                g_end = self.total
            for w in g:
                w["g_end"] = g_end

    def caption(self, img, t):
        cs = self.cap_style
        sc_i = None
        for gi, g in enumerate(self.groups):
            if g[0]["s"] - 0.04 <= t < g[0]["g_end"]:
                sc_i = gi
                break
        if sc_i is None:
            return
        g = self.groups[sc_i]
        sc = self.scenes[g[0]["scene"]]
        if not sc.caps:
            return
        cy = sc.cap_y or self.cap_y
        font = F(cs.get("font", "mont"), cs.get("size", 92), cs.get("wght", 900))
        upper = cs.get("upper", True)
        hi = cs.get("hi", (255, 214, 10))
        base = cs.get("fg", (255, 255, 255))
        stroke = cs.get("stroke", 11)
        cur = 0
        for k, w in enumerate(g):
            if t >= w["s"] - 0.03:
                cur = k
        words = [re.sub(r"[,;:]$", "", w["w"]) for w in g]
        if upper:
            words = [w.upper() for w in words]
        key = ("cap", tuple(words), cur, cs.get("font"), cs.get("size"))
        if key not in _layers:
            space = tw(" ", font)
            widths = [tw(w, font, stroke) for w in words]
            # wrap to <= 920
            lines, line, lw = [], [], 0
            for i, ww in enumerate(widths):
                if line and lw + space + ww > 920:
                    lines.append(line)
                    line, lw = [], 0
                lw += (space if line else 0) + ww
                line.append(i)
            lines.append(line)
            asc = font.getbbox("ÁGy", stroke_width=stroke)
            lh = asc[3] - asc[1] + 6
            Wd = 1000
            im = Image.new("RGBA", (Wd, lh * len(lines) + 40), (0, 0, 0, 0))
            dd = ImageDraw.Draw(im)
            for li, line in enumerate(lines):
                total = sum(widths[i] for i in line) + space * (len(line) - 1)
                x = (Wd - total) / 2
                for i in line:
                    col = hi if i == cur else base
                    if cs.get("box") and i == cur:
                        rrect(dd, (x - 14, 20 + li * lh - 4, x + widths[i] + 14, 20 + li * lh + lh), 18, fill=cs["box"])
                        col = cs.get("box_fg", (255, 255, 255))
                    dd.text((x - asc[0], 20 + li * lh - asc[1]), words[i], font=font, fill=col, stroke_width=stroke,
                            stroke_fill=cs.get("sfill", (0, 0, 0)))
                    x += widths[i] + space
            _layers[key] = im
        L = _layers[key]
        x = (t - g[0]["s"]) / 0.12
        s = lerp(0.82, 1.0, eo(x)) if x < 1 else 1.0
        paste_layer(img, L, W / 2, cy, scale=s)

    def frame(self, i):
        t = i / FPS
        acc = 0
        for sc in self.scenes:
            if t < acc + sc.dur or sc is self.scenes[-1]:
                break
            acc += sc.dur
        lt = t - sc.start
        img = Image.new("RGB", (W, H))
        sc.draw(img, ImageDraw.Draw(img, "RGBA"), lt, sc.dur, t)
        if self.overlay:
            self.overlay(img, ImageDraw.Draw(img, "RGBA"), t, self.total)
        self.caption(img, t)
        return img


def _render_part(args):
    mod, name, a, b, path = args
    import importlib
    v = getattr(importlib.import_module(mod), name)()
    v.build_audio()
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                          "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    for i in range(a, b):
        p.stdin.write(v.frame(i).tobytes())
    p.stdin.close()
    p.wait()
    return path


def render(mod, name, out, workdir, procs=4):
    import importlib
    import soundfile as sf
    v = getattr(importlib.import_module(mod), name)()
    v.build_audio()
    n = int(v.total * FPS)
    os.makedirs(workdir, exist_ok=True)
    cuts = [n * k // procs for k in range(procs + 1)]
    parts = [(mod, name, cuts[k], cuts[k + 1], f"{workdir}/{name}_{k}.mp4") for k in range(procs)]
    with Pool(procs) as pool:
        paths = pool.map(_render_part, parts)
    lst = f"{workdir}/{name}_list.txt"
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in paths)
    wav = f"{workdir}/{name}.wav"
    sf.write(wav, v.audio, SR)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-af", "highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=5:release=80,loudnorm=I=-14:TP=-1.5:LRA=7,aresample=48000",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out], check=True)
    return v


def contact(mod, name, out, per_scene=1):
    import importlib
    v = getattr(importlib.import_module(mod), name)()
    v.build_audio()
    frames = []
    for sc in v.scenes:
        for k in range(per_scene):
            t = sc.start + sc.dur * (k + 0.75) / per_scene
            frames.append(v.frame(int(t * FPS)).resize((270, 480)))
    cols = min(len(frames), 8)
    rows = math.ceil(len(frames) / cols)
    sheet = Image.new("RGB", (cols * 270, rows * 480), (255, 255, 255))
    for i, f in enumerate(frames):
        sheet.paste(f, ((i % cols) * 270, (i // cols) * 480))
    sheet.save(out)
    return v
