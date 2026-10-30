#!/usr/bin/env python3
"""Render a hand-animated wallpaper loop from a scene file.

    python3 tools/render.py scenes/night-city_widescreen.yml --preview
    python3 tools/render.py scenes/night-city_widescreen.yml --final
    python3 tools/render.py scenes/night-city_widescreen.yml --masks

Every effect is periodic over `loop_seconds`, so the last frame flows straight
into the first one. All coordinates in a scene file are pixels on the grid
given by `ref_size`; they're scaled to the source image and the output size.
"""
import argparse
import math
import os
import subprocess
import sys

import cv2
import numpy as np
import yaml
from scipy.spatial import cKDTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAU = 2 * math.pi


# ---------------------------------------------------------------- helpers

def luma(img):
    return img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722


def smoothstep(e0, e1, x):
    x = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return x * x * (3 - 2 * x)


def ellipse(r):
    r = max(1, int(round(r)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def blur(img, sigma):
    return cv2.GaussianBlur(img, (0, 0), max(0.3, sigma))


class Ctx:
    """Scene geometry at the size being rendered."""

    def __init__(self, scene, size, seed):
        self.W, self.H = size
        rw, rh = scene["ref_size"]
        self.k = self.W / rw  # ref pixels -> output pixels
        self.T = float(scene["loop_seconds"])
        self.fps = int(scene["fps"])
        self.rng = np.random.default_rng(seed)

        src = cv2.imread(os.path.join(ROOT, scene["source"]), cv2.IMREAD_COLOR)
        if src is None:
            sys.exit(f"can't read {scene['source']}")
        src = cv2.cvtColor(src, cv2.COLOR_BGR2RGB)
        interp = cv2.INTER_LANCZOS4 if self.W > src.shape[1] else cv2.INTER_AREA
        img = cv2.resize(src, (self.W, self.H), interpolation=interp).astype(np.float32) / 255
        if self.W > src.shape[1] * 1.15:
            # upscaled: a light unsharp mask keeps the city lights crisp
            img = np.clip(img + 0.35 * (img - blur(img, 1.2 * self.k / 1.7)), 0, 1)
        self.base = img
        self.luma = luma(img)

        self.protect = np.zeros((self.H, self.W), np.float32)
        for p in scene.get("protect", []):
            self.protect = np.maximum(self.protect, self.region_mask(p))
        self.protect = blur(self.protect, 2 * self.k)
        self.free = 1 - np.clip(self.protect * 1.5, 0, 1)

    def px(self, v):
        return v * self.k

    def pts(self, pts):
        return (np.asarray(pts, np.float32) * self.k)

    def rect_mask(self, r):
        x0, y0, x1, y1 = [int(round(v * self.k)) for v in r]
        m = np.zeros((self.H, self.W), np.float32)
        m[max(0, y0):y1, max(0, x0):x1] = 1
        return m

    def poly_mask(self, poly):
        m = np.zeros((self.H, self.W), np.uint8)
        cv2.fillPoly(m, [np.round(self.pts(poly)).astype(np.int32)], 1)
        return m.astype(np.float32)

    def lines_mask(self, lines, width):
        m = np.zeros((self.H, self.W), np.uint8)
        for ln in lines:
            cv2.polylines(m, [np.round(self.pts(ln)).astype(np.int32)], False, 1,
                          thickness=max(1, int(round(self.px(width)))))
        return m.astype(np.float32)

    def region_mask(self, r):
        """A region is {rect: [...]}, {poly: [...]} or {lines: [...], width},
        optionally limited to dark pixels (max_luma) or bright ones (min_luma)."""
        if "rect" in r:
            m = self.rect_mask(r["rect"])
        elif "poly" in r:
            m = self.poly_mask(r["poly"])
        else:
            m = self.lines_mask(r["lines"], r.get("width", 5))
        if "max_luma" in r:
            m *= (self.luma <= r["max_luma"]).astype(np.float32)
            m = cv2.dilate(m, ellipse(2 * self.k))
        if "min_luma" in r:
            m *= (self.luma >= r["min_luma"]).astype(np.float32)
        return m

    def regions(self, rs):
        m = np.zeros((self.H, self.W), np.float32)
        for r in rs:
            m = np.maximum(m, self.region_mask(r))
        return m


def bbox(mask, pad=0):
    ys, xs = np.nonzero(mask > 1e-3)
    if len(ys) == 0:
        return None
    H, W = mask.shape
    return (max(0, ys.min() - pad), min(H, ys.max() + pad + 1),
            max(0, xs.min() - pad), min(W, xs.max() + pad + 1))


def point_lights(ctx, region, cfg):
    """Small bright points (windows, stars, street lights) inside `region`.
    Returns (labels, n, layer): per-point labels and each point's light above
    its local background, in RGB."""
    r = ctx.px(cfg.get("size", 3))
    k = ellipse(r)
    opened = cv2.morphologyEx(ctx.base, cv2.MORPH_OPEN, k)
    layer = np.clip(ctx.base - opened, 0, None)
    th = luma(layer)
    m = ((th > cfg.get("threshold", 0.08)) & (region * ctx.free > 0.5)).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    max_area = cfg.get("max_area", 40) * ctx.k * ctx.k
    keep = (stats[:, cv2.CC_STAT_AREA] <= max_area)
    keep[0] = False
    # animate only a fraction of the points
    keep &= ctx.rng.random(n) < cfg.get("fraction", 1.0)
    remap = np.zeros(n, np.int32)
    remap[keep] = np.arange(1, keep.sum() + 1)
    labels = remap[labels]
    # grow each point a little so its glow fades with it
    grown = cv2.dilate(labels.astype(np.float32), ellipse(max(1, r * 0.6))).astype(np.int32)
    labels = np.where(labels > 0, labels, grown)
    layer *= (labels > 0)[..., None]
    return labels, int(keep.sum()), layer


# ---------------------------------------------------------------- effects
# Each effect: __init__(ctx, cfg) prepares masks; apply(frame, t) edits the
# frame in place. Anything that varies over time uses whole cycles per loop.

class Stars:
    """Faint stars twinkle. Stars are lifted off the sky first so the
    clouds can drift without dragging the stars along."""

    def __init__(self, ctx, cfg):
        region = ctx.regions(cfg["regions"])
        self.labels, n, self.layer = point_lights(ctx, region, cfg)
        ctx.base = ctx.base - self.layer
        lo, hi = cfg.get("cycles", [1, 3])
        self.cyc = ctx.rng.integers(lo, hi + 1, n + 1).astype(np.float32)
        self.ph = ctx.rng.random(n + 1).astype(np.float32)
        self.depth = cfg.get("depth", 0.8)
        self.T = ctx.T
        self.bb = bbox(self.labels)

    def apply(self, f, t):
        if self.bb is None:
            return
        y0, y1, x0, x1 = self.bb
        w = 0.5 - 0.5 * np.cos(TAU * (self.cyc * t / self.T + self.ph))
        g = 1 - self.depth * w ** 2
        g[0] = 0
        f[y0:y1, x0:x1] += self.layer[y0:y1, x0:x1] * g[self.labels[y0:y1, x0:x1]][..., None]


class Clouds:
    """Clouds drift sideways. Two copies of the sky slide along and crossfade
    (a flow-map loop), so the motion never has to jump back."""

    def __init__(self, ctx, cfg):
        H, W = ctx.H, ctx.W
        top, bottom = ctx.px(cfg["full_until"]), ctx.px(cfg["sky_bottom"])
        y = np.arange(H, dtype=np.float32)
        m = 1 - smoothstep(top, bottom, y)
        mask = np.repeat(m[:, None], W, 1)
        for h in cfg.get("hold", []):  # e.g. the moon stays put
            c = ctx.pts(h["center"])
            r = ctx.px(h["radius"])
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            d = np.hypot(xx - c[0], yy - c[1])
            mask *= smoothstep(r, r * 2.2, d)
        self.mask = mask
        self.rows = int(math.ceil(bottom)) + 2
        self.D = ctx.px(cfg["drift"]) * (-1 if cfg.get("direction", "left") == "left" else 1)
        self.P = ctx.T / cfg.get("crossfades_per_loop", 2)
        yy, xx = np.mgrid[0:self.rows, 0:W].astype(np.float32)
        self.xx, self.yy = xx, yy
        self.ctx = ctx

    def apply(self, f, t):
        src = self.ctx.base[:self.rows]
        m = self.mask[:self.rows]
        p1 = (t / self.P) % 1.0
        out = 0
        for p in (p1, (p1 + 0.5) % 1.0):
            w = 1 - abs(2 * p - 1)
            mx = self.xx - (p - 0.5) * self.D * m
            out = out + w * cv2.remap(src, mx, self.yy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        mm = m[..., None] > 0
        f[:self.rows] = np.where(mm, out, f[:self.rows])


class MoonGlow:
    """The halo around the moon slowly breathes."""

    def __init__(self, ctx, cfg):
        c = ctx.pts(cfg["center"])
        R = ctx.px(cfg["glow_radius"])
        r = ctx.px(cfg["radius"])
        yy, xx = np.mgrid[0:ctx.H, 0:ctx.W].astype(np.float32)
        d = np.hypot(xx - c[0], yy - c[1])
        g = np.exp(-np.maximum(d - r * 0.8, 0) ** 2 / (2 * (R / 2.2) ** 2))
        col = np.array(cfg.get("color", [0.85, 0.78, 1.0]), np.float32)
        self.glow = g[..., None] * col
        self.bb = bbox(g > 0.01)
        self.s = cfg.get("strength", 0.2)
        self.cyc = cfg.get("cycles", 2)
        self.T = ctx.T

    def apply(self, f, t):
        a = self.s * (0.5 - 0.5 * math.cos(TAU * self.cyc * t / self.T))
        y0, y1, x0, x1 = self.bb
        sub = f[y0:y1, x0:x1]
        f[y0:y1, x0:x1] = 1 - (1 - sub) * (1 - a * self.glow[y0:y1, x0:x1])


class Lights:
    """Lit windows / house lights. Some fade off for a few seconds now and
    then (mode: fade); others gently twinkle (mode: twinkle)."""

    def __init__(self, ctx, cfg):
        region = ctx.regions(cfg["regions"])
        self.labels, n, self.layer = point_lights(ctx, region, cfg)
        self.mode = cfg.get("mode", "fade")
        lo, hi = cfg.get("cycles", [1, 2])
        self.cyc = ctx.rng.integers(lo, hi + 1, n + 1).astype(np.float32)
        self.ph = ctx.rng.random(n + 1).astype(np.float32)
        dlo, dhi = cfg.get("off_fraction", [0.15, 0.35])
        self.duty = (dlo + (dhi - dlo) * ctx.rng.random(n + 1)).astype(np.float32)
        self.depth = cfg.get("depth", 0.85)
        self.T = ctx.T
        self.fade = cfg.get("fade_seconds", 0.8)
        self.bb = bbox(self.labels)
        self.n = n

    def gain(self, t):
        u = (self.cyc * t / self.T + self.ph) % 1.0
        if self.mode == "twinkle":
            w = (0.5 - 0.5 * np.cos(TAU * u)) ** 3
            return 1 - self.depth * w
        # off between u=0 and u=duty, with soft edges
        period = self.T / self.cyc
        e = np.minimum(self.fade / period, self.duty / 2)
        off = smoothstep(0, e, u) * (1 - smoothstep(self.duty - e, self.duty, u))
        return 1 - self.depth * off

    def apply(self, f, t):
        if self.bb is None:
            return
        y0, y1, x0, x1 = self.bb
        g = self.gain(t) - 1
        g[0] = 0
        f[y0:y1, x0:x1] += self.layer[y0:y1, x0:x1] * g[self.labels[y0:y1, x0:x1]][..., None]


class Neon:
    """Neon structures (the red bridge towers): a slow pulse, a soft bloom
    and a rare quick flicker."""

    def __init__(self, ctx, cfg):
        self.items = []
        b = ctx.base
        red = smoothstep(0.03, 0.15, b[..., 0] - np.maximum(b[..., 1], b[..., 2] * 0.9))
        bright = smoothstep(cfg.get("min_luma", 0.25), cfg.get("min_luma", 0.25) + 0.15, ctx.luma)
        self.T = ctx.T
        # the neon's own light, above what's behind it: dimming it reveals the
        # city behind rather than a dull, darkened tube
        behind = cv2.morphologyEx(b, cv2.MORPH_OPEN, ellipse(ctx.px(cfg.get("tube_width", 6))))
        own = np.clip(b - behind, 0, None)
        for it in cfg["items"]:
            m = ctx.region_mask(it) * red * bright * ctx.free
            m = blur(m, 0.7 * ctx.k)
            layer = own * m[..., None]
            bloom = blur(layer, ctx.px(cfg.get("bloom_radius", 6)))
            bb = bbox(blur(m, ctx.px(cfg.get("bloom_radius", 6)) * 2) > 0.002)
            self.items.append(dict(layer=layer, bloom=bloom, bb=bb,
                                   phase=it.get("phase", 0.0),
                                   flickers=it.get("flickers", [])))
        self.pulse = cfg.get("pulse", 0.12)
        self.pulse_cycles = cfg.get("pulse_cycles", 2)
        self.bloom = cfg.get("bloom", 0.5)

    def gain(self, it, t):
        g = 1 + self.pulse * math.sin(TAU * (self.pulse_cycles * t / self.T + it["phase"]))
        for fl in it["flickers"]:  # [time, seconds, depth]
            t0, dur, depth = fl
            dt = (t - t0) % self.T
            if dt < dur:
                # a stuttery dip: a couple of quick off/on blinks
                g *= 1 - depth * (0.6 + 0.4 * math.sin(TAU * dt / dur * 3) ** 2)
        return g

    def apply(self, f, t):
        for it in self.items:
            if it["bb"] is None:
                continue
            y0, y1, x0, x1 = it["bb"]
            g = self.gain(it, t)
            f[y0:y1, x0:x1] += it["layer"][y0:y1, x0:x1] * (g - 1) + it["bloom"][y0:y1, x0:x1] * self.bloom * g


class Traffic:
    """Pulses of light travel along the lit roads, like traffic. Only the
    road's own light gets brighter, so the colours stay the edit's own."""

    def __init__(self, ctx, cfg):
        self.T = ctx.T
        self.paths = []
        for p in cfg["paths"]:
            pts = ctx.pts(p["points"])
            seg = np.diff(pts, axis=0)
            seglen = np.hypot(seg[:, 0], seg[:, 1])
            L = float(seglen.sum())
            # dense samples along the path, each with its distance s
            ss, xy = [], []
            acc = 0.0
            for a, d, l in zip(pts[:-1], seg, seglen):
                k = max(2, int(l))
                u = np.linspace(0, 1, k, endpoint=False)
                xy.append(a + u[:, None] * d)
                ss.append(acc + u * l)
                acc += l
            xy = np.concatenate(xy)
            ss = np.concatenate(ss)
            band = np.zeros((ctx.H, ctx.W), np.uint8)
            cv2.polylines(band, [np.round(pts).astype(np.int32)], False, 1,
                          thickness=max(1, int(round(ctx.px(p.get("width", 14))))))
            road = smoothstep(cfg.get("min_luma", 0.3), cfg.get("min_luma", 0.3) + 0.25, ctx.luma)
            m = band * road * ctx.free
            ys, xs = np.nonzero(m > 0.01)
            _, idx = cKDTree(xy).query(np.stack([xs, ys], 1).astype(np.float32))
            s = ss[idx].astype(np.float32)
            n = p.get("pulses", 6)
            spacing = L / n
            speed = ctx.px(p.get("speed", 60))  # px per second
            cyc = max(1, round(speed * self.T / spacing))  # whole spacings per loop
            self.paths.append(dict(
                ys=ys, xs=xs, u=s / spacing, w=ctx.px(p.get("pulse_length", 30)) / spacing,
                cyc=cyc * (1 if p.get("direction", "forward") == "forward" else -1),
                rgb=ctx.base[ys, xs] * m[ys, xs][:, None], strength=p.get("strength", 0.6)))

    def apply(self, f, t):
        for p in self.paths:
            d = (p["u"] - p["cyc"] * t / self.T) % 1.0
            d = np.minimum(d, 1 - d)
            pulse = np.exp(-(d / p["w"]) ** 2)
            f[p["ys"], p["xs"]] += p["rgb"] * (p["strength"] * pulse)[:, None]


class Water:
    """Reflections on the water shimmer with a gentle sideways ripple."""

    def __init__(self, ctx, cfg):
        m = ctx.regions(cfg["regions"])
        for ex in cfg.get("exclude", []):
            m *= 1 - ctx.region_mask(ex)
        m = blur(m * ctx.free, ctx.px(3))
        self.bb = bbox(m, pad=4)
        y0, y1, x0, x1 = self.bb
        self.m = m[y0:y1, x0:x1]
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        self.xx, self.yy = xx, yy
        self.amp = ctx.px(cfg.get("amplitude", 1.5))
        self.lam = ctx.px(cfg.get("wavelength", 7))
        self.cyc = cfg.get("cycles", 12)
        self.T = ctx.T
        self.ctx = ctx

    def apply(self, f, t):
        y0, y1, x0, x1 = self.bb
        ph = TAU * self.cyc * t / self.T
        dx = self.amp * (np.sin(TAU * self.yy / self.lam - ph) * 0.7
                         + 0.3 * np.sin(TAU * (self.yy / (self.lam * 2.3) + self.xx / (self.lam * 31)) + ph))
        src = f[y0:y1, x0:x1].copy()
        mx = (self.xx - x0 + dx * self.m).astype(np.float32)
        my = (self.yy - y0).astype(np.float32)
        rip = cv2.remap(src, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        f[y0:y1, x0:x1] = src + (rip - src) * self.m[..., None]


# order matters: stars come off the sky before the clouds move
EFFECTS = [("stars", Stars), ("clouds", Clouds), ("moon_glow", MoonGlow),
           ("window_lights", Lights), ("house_lights", Lights), ("bridge_neon", Neon),
           ("traffic", Traffic), ("water", Water)]


def build(scene, size):
    ctx = Ctx(scene, size, scene.get("seed", 7))
    fx = []
    for key, cls in EFFECTS:
        cfg = scene["effects"].get(key)
        if cfg and cfg.get("enabled", True):
            fx.append((key, cls(ctx, cfg)))
    return ctx, fx


def frame(ctx, fx, t):
    f = ctx.base.copy()
    for _, e in fx:
        e.apply(f, t)
    return np.clip(f, 0, 1)


# ---------------------------------------------------------------- output

def encode(ctx, fx, path, seconds, final):
    n = int(round(seconds * ctx.fps))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb48le",
           "-s", f"{ctx.W}x{ctx.H}", "-r", str(ctx.fps), "-i", "-",
           "-vf", "scale=out_color_matrix=bt709:out_range=tv",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-movflags", "+faststart"]
    if final:
        # HEVC Main10: hardware-decoded on Apple Silicon; 10-bit keeps the sky free of banding
        cmd += ["-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-profile:v", "main10",
                "-preset", "slow", "-crf", "18", "-tag:v", "hvc1",
                "-x265-params", f"keyint={ctx.fps * 2}:log-level=error"]
    else:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium"]
    cmd.append(path)
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    rng = np.random.default_rng(0)
    for i in range(n):
        f = frame(ctx, fx, (i / ctx.fps) % ctx.T)
        # tiny dither so the smooth sky doesn't band
        f = f * 65535 + rng.uniform(-96, 96, f.shape).astype(np.float32)
        p.stdin.write(np.clip(f, 0, 65535).astype("<u2").tobytes())
        if i % 60 == 0:
            print(f"  frame {i}/{n}", flush=True)
    p.stdin.close()
    if p.wait() != 0:
        sys.exit("ffmpeg failed")


def check_seam(ctx, fx):
    """The frame one step past the end must match frame 0 exactly."""
    a = frame(ctx, fx, 0.0)
    b = frame(ctx, fx, ctx.T)
    return float(np.abs(a - b).max())


def save_masks(ctx, fx, outdir):
    os.makedirs(outdir, exist_ok=True)
    over = ctx.base.copy() * 0.45
    colours = {"stars": (1, 1, 1), "clouds": (0.3, 0.6, 1), "moon_glow": (1, 1, 0.6),
               "window_lights": (0, 1, 0.4), "house_lights": (0, 0.8, 1),
               "bridge_neon": (1, 0.1, 0.4), "traffic": (1, 1, 0), "water": (0.2, 0.4, 1)}
    for key, e in fx:
        c = np.array(colours[key], np.float32)
        if isinstance(e, (Stars, Lights)):
            m = (e.labels > 0).astype(np.float32)
        elif isinstance(e, Clouds):
            m = np.zeros((ctx.H, ctx.W), np.float32)
            m[:e.rows] = e.mask[:e.rows] * 0.35
        elif isinstance(e, MoonGlow):
            m = luma(e.glow) * 0.5
        elif isinstance(e, Neon):
            m = sum(np.clip(luma(i["layer"]) * 6, 0, 1) for i in e.items)
        elif isinstance(e, Traffic):
            m = np.zeros((ctx.H, ctx.W), np.float32)
            for p in e.paths:
                m[p["ys"], p["xs"]] = 1
        else:
            m = np.zeros((ctx.H, ctx.W), np.float32)
            y0, y1, x0, x1 = e.bb
            m[y0:y1, x0:x1] = e.m * 0.6
        over = over * (1 - m[..., None]) + c * m[..., None]
        cv2.imwrite(os.path.join(outdir, f"{key}.png"), (np.clip(m, 0, 1) * 255).astype(np.uint8))
    over = over * (1 - ctx.protect[..., None] * 0.6) + np.array([1, 0, 0]) * ctx.protect[..., None] * 0.6
    cv2.imwrite(os.path.join(outdir, "_overview.jpg"),
                cv2.cvtColor((np.clip(over, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--preview", action="store_true", help="small H.264 preview")
    g.add_argument("--final", action="store_true", help="native-resolution HEVC loop per screen")
    g.add_argument("--masks", action="store_true", help="write effect masks to masks/<scene>/")
    g.add_argument("--still", type=float, metavar="SECONDS", help="one frame as PNG")
    ap.add_argument("--seconds", type=float, help="preview length (default: whole loop)")
    a = ap.parse_args()

    with open(a.scene) as fh:
        scene = yaml.safe_load(fh)
    stem = os.path.splitext(os.path.basename(a.scene))[0]
    rw, rh = scene["ref_size"]

    if a.final:
        os.makedirs(os.path.join(ROOT, "loops"), exist_ok=True)
        for out in scene["outputs"]:
            size = tuple(out["size"])
            ctx, fx = build(scene, size)
            seam = check_seam(ctx, fx)
            path = os.path.join(ROOT, "loops", f"{scene['name']}_{out['screen']}.mp4")
            print(f"{path}: {size[0]}x{size[1]}, seam error {seam:.2e}")
            encode(ctx, fx, path, ctx.T, final=True)
        return

    pw = scene.get("preview_width", 1280)
    size = (pw, int(round(pw * rh / rw / 2)) * 2)
    ctx, fx = build(scene, size)
    if a.masks:
        save_masks(ctx, fx, os.path.join(ROOT, "masks", stem))
    elif a.still is not None:
        os.makedirs(os.path.join(ROOT, "previews"), exist_ok=True)
        f = frame(ctx, fx, a.still)
        cv2.imwrite(os.path.join(ROOT, "previews", f"{stem}_t{a.still:g}.png"),
                    cv2.cvtColor((f * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))
    else:
        os.makedirs(os.path.join(ROOT, "previews"), exist_ok=True)
        path = os.path.join(ROOT, "previews", f"{stem}_preview.mp4")
        print(f"{path}: seam error {check_seam(ctx, fx):.2e}")
        encode(ctx, fx, path, a.seconds or ctx.T, final=False)


if __name__ == "__main__":
    main()
