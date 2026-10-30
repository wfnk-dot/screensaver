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

    def beat(self, t, at, period, attack=0.08, decay=0.6):
        """A flash that peaks at `at` seconds and repeats every `period`:
        a quick rise, then a fade. Periodic, so loops stay seamless."""
        dt = (t - at + attack) % period
        if dt < attack:
            return smoothstep(0, attack, dt) if attack > 0 else 1.0
        return math.exp(-(dt - attack) / decay)

    def tracer_hit(self, ref_pt):
        """When (seconds into each lap) the road tracer passes the road point
        nearest to `ref_pt`, and how often it comes by. None if no tracer."""
        tr = getattr(self, "tracer", None)
        if tr is None:
            return None
        if ref_pt == "end":
            s = tr["L"]
        else:
            d = np.hypot(*(tr["xy"] - self.pts(ref_pt)).T)
            s = tr["ss"][int(np.argmin(d))]
        period = self.T / (tr["cyc"] * tr["heads"])
        return (s / tr["spacing"]) * self.T / tr["cyc"] % period, period

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
        self.lo, self.hi = cfg.get("range", [0.1, 1.6])
        self.T = ctx.T
        self.bb = bbox(self.labels)

    def apply(self, f, t):
        if self.bb is None:
            return
        y0, y1, x0, x1 = self.bb
        w = 0.5 - 0.5 * np.cos(TAU * (self.cyc * t / self.T + self.ph))
        g = self.lo + (self.hi - self.lo) * w ** 2
        g[0] = 0
        f[y0:y1, x0:x1] += self.layer[y0:y1, x0:x1] * g[self.labels[y0:y1, x0:x1]][..., None]


class Clouds:
    """Clouds scroll across the sky like a time-lapse. The clouds are lifted
    off the clear-sky colour, made to tile seamlessly left to right, and slide
    exactly one tile per `scrolls_per_loop`, so the loop never jumps."""

    def __init__(self, ctx, cfg):
        W = ctx.W
        top, bottom = ctx.px(cfg["full_until"]), ctx.px(cfg["sky_bottom"])
        self.rows = rows = int(math.ceil(bottom)) + 2
        y = np.arange(rows, dtype=np.float32)
        self.m = (1 - smoothstep(top, bottom, y))[:, None, None]
        sky = ctx.base[:rows]

        # clear-sky colour per row, plus the sky's broad left-right glow
        clear = np.percentile(sky, cfg.get("clear_percentile", 20), axis=1).astype(np.float32)
        clear = cv2.GaussianBlur(clear[:, None, :], (0, 0), sigmaX=0.1, sigmaY=ctx.px(6))[:, 0, :]
        r = sky - clear[:, None, :]
        r -= blur(r, W / 6)

        # the moon stays where it is: take it out of the moving layer and
        # fill the hole from the clouds around it
        hold = np.zeros((rows, W), np.float32)
        yy, xx = np.mgrid[0:rows, 0:W].astype(np.float32)
        for h in cfg.get("hold", []):
            c, rad = ctx.pts(h["center"]), ctx.px(h["radius"])
            d = np.hypot(xx - c[0], yy - c[1])
            hold = np.maximum(hold, 1 - smoothstep(rad * 1.1, rad * 1.8, d))
        keep = (1 - hold)[..., None]
        # borrow real cloud texture from beside the moon
        fill = np.roll(r, int(ctx.px(cfg.get("fill_offset", 140))), axis=1)
        self.r0 = r * keep * self.m          # what's removed from the still image
        moving = r * keep + fill * (1 - keep)

        # make it tile: blend the last `S` columns into the first ones
        S = int(W * cfg.get("seam_blend", 0.18))
        P = W - S
        a = smoothstep(0, 1, np.linspace(0, 1, S, dtype=np.float32))[None, :, None]
        tile = moving[:, :P].copy()
        tile[:, :S] = a * moving[:, :S] + (1 - a) * moving[:, P:P + S]
        self.tile = tile * self.m
        self.P = P
        self.dist = P * cfg.get("scrolls_per_loop", 1)
        self.sign = 1 if cfg.get("direction", "left") == "left" else -1
        self.gain = cfg.get("contrast", 1.0)
        self.x = np.arange(W, dtype=np.float64)
        self.T = ctx.T
        ctx.sky_bottom = bottom
        self.flashes = cfg.get("lightning", [])     # [[time, seconds, strength]]
        self.soft = lambda img, s=ctx.px(4): blur(img, s)
        self.flash_col = np.array(cfg.get("lightning_color", [0.75, 0.5, 1.0]), np.float32)
        # how much each strike lights the whole scene, sky to ground
        self.ambient = cfg.get("lightning_ambient", 0.0)
        if self.ambient:
            # distant lightning: the sky takes the most, the far city a
            # little, the foreground almost nothing
            y = np.arange(ctx.H, dtype=np.float32)
            y0f, y1f = cfg.get("lightning_fade", [cfg["sky_bottom"], cfg["sky_bottom"] * 2.2])
            fall = 1 - 0.97 * smoothstep(ctx.px(y0f), ctx.px(y1f), y)
            self.amb_map = (fall[:, None] * ctx.free)[..., None] * self.flash_col

    def apply(self, f, t):
        s = self.sign * self.dist * t / self.T
        u = (self.x + s) % self.P
        i0 = np.floor(u).astype(np.int64)
        fr = (u - i0).astype(np.float32)[None, :, None]
        i1 = (i0 + 1) % self.P
        moved = self.tile[:, i0] * (1 - fr) + self.tile[:, i1] * fr
        f[:self.rows] += moved * self.gain - self.r0
        for t0, dur, k in self.flashes:
            dt = (t - t0) % self.T
            if dt < dur:
                # a double flicker lighting the clouds from inside
                e = k * (math.sin(math.pi * dt / dur) ** 0.5) * (0.55 + 0.45 * math.cos(TAU * 2.5 * dt / dur))
                lit = np.clip(self.soft(moved), 0, None).sum(-1, keepdims=True) * 3 + 0.08
                f[:self.rows] += e * lit * self.flash_col * self.m
                if self.ambient:
                    f += e * self.ambient * self.amb_map * (0.35 + f)


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
        self.ctx = ctx
        # sync: the moon flares when the road light reaches the end of the road
        self.sync = None
        sy = cfg.get("sync")
        if sy and ctx.tracer_hit("end"):
            at, period = ctx.tracer_hit("end")
            self.sync = (at + sy.get("delay", 0.2), period, sy.get("rest", 0.3), sy.get("sharpness", 1.5))

    def apply(self, f, t):
        if self.sync:
            # a slow swell that peaks just after the road light arrives
            at, period, rest, sharp = self.sync
            w = (0.5 + 0.5 * math.cos(TAU * (t - at) / period)) ** sharp
            a = self.s * (rest + (1 - rest) * w)
        else:
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
            hit = None
            if cfg.get("flash_on_tracer") and "lines" in it:
                ctr = np.mean([pt for ln in it["lines"] for pt in ln], axis=0)
                foot = [ctr[0], max(pt[1] for ln in it["lines"] for pt in ln)]
                hit = ctx.tracer_hit(foot)
            self.items.append(dict(layer=layer, bloom=bloom, bb=bb, hit=hit,
                                   phase=it.get("phase", 0.0),
                                   flickers=it.get("flickers", [])))
        self.flash = cfg.get("flash_on_tracer", 0)
        self.ctx = ctx
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
        if it["hit"]:
            at, period = it["hit"]
            g += self.flash * self.ctx.beat(t, at, period, 0.12, 0.7)
        return g

    def apply(self, f, t):
        for it in self.items:
            if it["bb"] is None:
                continue
            y0, y1, x0, x1 = it["bb"]
            g = self.gain(it, t)
            f[y0:y1, x0:x1] += it["layer"][y0:y1, x0:x1] * (g - 1) + it["bloom"][y0:y1, x0:x1] * self.bloom * g


class Traffic:
    """Light travels along the lit roads: either one neon tracer running the
    whole road (mode: tracer), or many traffic-like pulses. Only the road's
    own light gets brighter, so the colours stay the edit's own."""

    def __init__(self, ctx, cfg):
        self.T = ctx.T
        self.paths = []
        for p in cfg["paths"]:
            p = dict(p, **cfg.get("all_paths", {}))
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
            lo = cfg.get("min_luma", 0.3)
            road = smoothstep(lo, lo + 0.25, ctx.luma)
            if p.get("fill"):
                # the whole lit road: pixels clearly brighter than the city
                # around it, joined to the line, so wide stretches fill edge
                # to edge and nothing off the road lights up
                fl = p.get("fill_luma", 0.48)
                lit = ((ctx.luma > fl) & (band > 0)).astype(np.uint8)
                n, lab = cv2.connectedComponents(lit, connectivity=8)
                spine = np.zeros_like(lit)
                cv2.polylines(spine, [np.round(pts).astype(np.int32)], False, 1,
                              thickness=max(1, int(round(ctx.px(4)))))
                on = np.unique(lab[(spine > 0) & (lit > 0)])
                keep = np.isin(lab, on[on > 0]).astype(np.float32)
                for r in p.get("fill_area", []):
                    # junctions: everything road-bright in the box joined to
                    # the road (ramps, both carriageways) lights up together
                    box = ctx.region_mask(r)
                    lit2 = ((ctx.luma > r.get("luma", fl)) & (box > 0)).astype(np.uint8)
                    n2, lab2 = cv2.connectedComponents(lit2, connectivity=8)
                    on2 = np.unique(lab2[(cv2.dilate(keep, ellipse(ctx.px(1))) > 0) & (lit2 > 0)])
                    keep = np.maximum(keep, np.isin(lab2, on2[on2 > 0]).astype(np.float32))
                    band = np.maximum(band, (box > 0).astype(band.dtype))
                # feather into the road's slightly dimmer edges
                near = cv2.dilate(keep, ellipse(ctx.px(1.5)))
                road = np.maximum(keep, near * smoothstep(fl - 0.12, fl, ctx.luma)) * band
            m = band * road * ctx.free
            ys, xs = np.nonzero(m > 0.01)
            _, idx = cKDTree(xy).query(np.stack([xs, ys], 1).astype(np.float32))
            s = ss[idx].astype(np.float32)
            rgb = ctx.base[ys, xs]
            nc = p.get("neon_color", cfg.get("neon_color"))
            if nc == "lift":
                neon = "lift"
            elif nc == "road":
                # the road's own hue at full saturation: neon, not white
                sat = rgb - rgb.min(1, keepdims=True) * 0.85
                neon = sat / np.maximum(sat.max(1, keepdims=True), 1e-3)
            elif nc is not None:
                neon = np.broadcast_to(np.array(nc, np.float32), rgb.shape)
            else:
                neon = None
            common = dict(ys=ys, xs=xs, rgb=rgb * m[ys, xs][:, None], m=m[ys, xs], neon=neon, base=rgb,
                          strength=p.get("strength", 0.6))
            if p.get("mode") == "tracer":
                # one light runs the whole road, then a short pause, then again
                spacing = L * (1 + p.get("gap", 0.25))
                heads = p.get("heads", 1)
                self.paths.append(dict(common, tracer=True, u=s / spacing, cyc=p.get("laps", 3),
                                       heads=heads,
                                       tail=ctx.px(p.get("tail", 300)) / spacing,
                                       head=ctx.px(p.get("head", 20)) / spacing))
                if not hasattr(ctx, "tracer"):
                    ctx.tracer = dict(xy=xy, ss=ss, L=L, spacing=spacing,
                                      cyc=p.get("laps", 3), heads=heads)
                continue
            n = p.get("pulses", 6)
            spacing = L / n
            speed = ctx.px(p.get("speed", 60))  # px per second
            cyc = max(1, round(speed * self.T / spacing))  # whole spacings per loop
            self.paths.append(dict(
                common, tracer=False, u=s / spacing, w=ctx.px(p.get("pulse_length", 30)) / spacing,
                cyc=cyc * (1 if p.get("direction", "forward") == "forward" else -1)))
        self.glow = cfg.get("glow", 0.0)
        self.glow_r = ctx.px(cfg.get("glow_radius", 5))
        pad = int(self.glow_r * 3) + 1
        ys = np.concatenate([p["ys"] for p in self.paths])
        xs = np.concatenate([p["xs"] for p in self.paths])
        self.bb = (max(0, ys.min() - pad), min(ctx.H, ys.max() + pad + 1),
                   max(0, xs.min() - pad), min(ctx.W, xs.max() + pad + 1))
        self.rest_dim = cfg.get("rest_dim", 0.0)
        y0, y1, x0, x1 = self.bb
        self.road_m = np.zeros((y1 - y0, x1 - x0, 1), np.float32)
        for p in self.paths:
            self.road_m[p["ys"] - y0, p["xs"] - x0, 0] = np.maximum(
                self.road_m[p["ys"] - y0, p["xs"] - x0, 0], p["m"])

    def apply(self, f, t):
        y0, y1, x0, x1 = self.bb
        buf = np.zeros((y1 - y0, x1 - x0, 3), np.float32)
        cover = np.zeros((y1 - y0, x1 - x0, 1), np.float32)
        spill = np.zeros_like(buf)
        for p in self.paths:
            if p["tracer"]:
                pulse = 0
                for h in range(p["heads"]):
                    behind = (p["cyc"] * t / self.T + h / p["heads"] - p["u"]) % 1.0
                    ahead = 1 - behind
                    pulse = pulse + np.where(behind < 0.5, np.exp(-behind / p["tail"]),
                                             np.exp(-(ahead / p["head"]) ** 2))
            else:
                d = (p["u"] - p["cyc"] * t / self.T) % 1.0
                d = np.minimum(d, 1 - d)
                pulse = np.exp(-(d / p["w"]) ** 2)
            if isinstance(p["neon"], str):
                # "lift": the road's own light gets brighter, keeping its
                # colour and texture; whatever can't fit spills into a glow
                g = 1 + p["strength"] * pulse * p["m"]
                room = 1 / np.maximum(p["base"].max(1), 1e-3)
                ge = np.minimum(g, room)
                yy, xx = p["ys"] - y0, p["xs"] - x0
                buf[yy, xx] += p["base"] * (ge - 1)[:, None]
                spill[yy, xx] += p["base"] * (p.get("spill", 0.3) * ((g - ge) + 0.5 * pulse * p["m"]))[:, None]
            elif p["neon"] is not None:
                # the lit stretch of road takes on the neon colour
                a = np.clip(pulse * p["strength"], 0, 0.95) * p["m"]
                cover[p["ys"] - y0, p["xs"] - x0, 0] = np.maximum(cover[p["ys"] - y0, p["xs"] - x0, 0], a)
                buf[p["ys"] - y0, p["xs"] - x0] += p["neon"] * a[:, None]
            else:
                buf[p["ys"] - y0, p["xs"] - x0] += p["rgb"] * (p["strength"] * pulse)[:, None]
        sub = f[y0:y1, x0:x1]
        if self.rest_dim:
            # the unlit road sits a little darker, like an unlit tube
            sub = sub * (1 - self.rest_dim * self.road_m)
        f[y0:y1, x0:x1] = sub * (1 - cover) + buf
        if spill.any():
            f[y0:y1, x0:x1] += blur(spill, self.glow_r) * self.glow
        elif self.glow:
            # the neon's glow spilling onto the city around it
            f[y0:y1, x0:x1] += blur(buf, self.glow_r) * self.glow


class Water:
    """Reflections on the water sway and glitter. A handful of long, low
    waves at odd angles add up to an irregular, natural-looking ripple."""

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
        r = ctx.rng
        n = cfg.get("waves", 6)
        lo, hi = cfg.get("wavelength", [6, 14])          # across the ripples (vertical)
        self.waves = []
        for i in range(n):
            ly = ctx.px(r.uniform(lo, hi))
            lx = ctx.px(r.uniform(150, 600)) * r.choice([-1, 1])
            spatial = (TAU * (yy / ly + xx / lx) + r.uniform(0, TAU)).astype(np.float32)
            self.waves.append((spatial, int(r.integers(*cfg.get("cycles", [8, 16])))))
        self.amp = ctx.px(cfg.get("amplitude", 2.0)) / math.sqrt(n)
        self.glint = cfg.get("glint", 0.0)
        self.T = ctx.T

    def apply(self, f, t):
        y0, y1, x0, x1 = self.bb
        dx = 0
        for spatial, c in self.waves:
            dx = dx + np.sin(spatial - TAU * c * t / self.T)
        src = f[y0:y1, x0:x1].copy()
        mx = (self.xx - x0 + self.amp * dx * self.m).astype(np.float32)
        my = (self.yy - y0).astype(np.float32)
        rip = cv2.remap(src, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        if self.glint:
            # crests catch the light
            g = np.clip(dx / 2.2, -1, 1)
            lit = smoothstep(0.3, 0.7, luma(src))[..., None]   # only the reflections
            rip = rip * (1 + self.glint * g[..., None] * lit)
        f[y0:y1, x0:x1] = src + (rip - src) * self.m[..., None]


def sprite_sparkle(R):
    """A four-point star like the ones on Wyn's Discord banner."""
    n = int(math.ceil(R)) * 2 + 1
    c = n // 2
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) - c
    w = max(0.6, R * 0.06)
    arms = (np.exp(-yy ** 2 / (2 * w * w)) * np.clip(1 - np.abs(xx) / R, 0, 1) ** 2
            + np.exp(-xx ** 2 / (2 * w * w)) * np.clip(1 - np.abs(yy) / R, 0, 1) ** 2)
    core = np.exp(-(xx ** 2 + yy ** 2) / (2 * (R * 0.12) ** 2))
    halo = np.exp(-(xx ** 2 + yy ** 2) / (2 * (R * 0.35) ** 2)) * 0.25
    return np.clip(arms + core + halo, 0, 1.5)


def sprite_dot(R):
    n = int(math.ceil(R * 3)) * 2 + 1
    c = n // 2
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) - c
    d2 = xx ** 2 + yy ** 2
    return np.exp(-d2 / (2 * (R * 0.35) ** 2)) + 0.35 * np.exp(-d2 / (2 * R ** 2))


def stamp(f, spr, x, y, rgb):
    """Add a sprite centred at (x, y), with sub-pixel placement."""
    n = spr.shape[0]
    ix, iy = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - ix, y - iy
    M = np.float32([[1, 0, fx], [0, 1, fy]])
    s = cv2.warpAffine(spr, M, (n + 1, n + 1))
    x0, y0 = ix - n // 2, iy - n // 2
    H, W = f.shape[:2]
    a0, b0 = max(0, -y0), max(0, -x0)
    a1, b1 = min(n + 1, H - y0), min(n + 1, W - x0)
    if a1 <= a0 or b1 <= b0:
        return
    f[y0 + a0:y0 + a1, x0 + b0:x0 + b1] += s[a0:a1, b0:b1, None] * rgb


class Sparkles:
    """Now and then a star flares into a four-point sparkle."""

    def __init__(self, ctx, cfg):
        reg = ctx.regions(cfg["regions"])
        if cfg.get("avoid"):
            reg *= 1 - ctx.regions(cfg["avoid"])
        L = ctx.luma * reg * ctx.free
        # brightest local peaks, kept apart from each other
        peaks = (L == cv2.dilate(L, ellipse(ctx.px(25)))) & (L > 0.05)
        ys, xs = np.nonzero(peaks)
        order = np.argsort(-L[ys, xs])[:cfg.get("count", 12)]
        self.pos = np.stack([xs[order], ys[order]], 1).astype(np.float32)
        n = len(self.pos)
        self.spr = sprite_sparkle(ctx.px(cfg.get("size", 14)))
        self.cyc = ctx.rng.integers(1, cfg.get("max_flares", 2) + 1, n)
        self.ph = ctx.rng.random(n)
        self.dur = cfg.get("flare_seconds", 1.6)
        self.col = np.array(cfg.get("color", [0.95, 0.85, 1.0]), np.float32)
        self.s = cfg.get("strength", 1.0)
        self.T = ctx.T

    def apply(self, f, t):
        for (x, y), k, ph in zip(self.pos, self.cyc, self.ph):
            period = self.T / k
            u = ((t / period + ph) % 1.0) * period
            if u < self.dur:
                e = math.sin(math.pi * u / self.dur) ** 2
                stamp(f, self.spr * e, x, y, self.col * self.s)


class Fireflies:
    """Soft glowing specks floating in the air, like the banner's."""

    def __init__(self, ctx, cfg):
        x0, y0, x1, y1 = [v * ctx.k for v in cfg["area"]]
        n = cfg.get("count", 20)
        r = ctx.rng
        self.base = np.stack([r.uniform(x0, x1, n), r.uniform(y0, y1, n)], 1)
        self.amp = np.stack([r.uniform(0.5, 1, n), r.uniform(0.5, 1, n)], 1) * ctx.px(cfg.get("wander", 40))
        self.k = r.integers(1, 3, (n, 2))
        self.ph = r.random((n, 2))
        self.bk = r.integers(1, 4, n)
        self.bph = r.random(n)
        sizes = cfg.get("size", [3, 6])
        self.spr = [sprite_dot(ctx.px(r.uniform(*sizes))) for _ in range(n)]
        cols = np.array(cfg.get("colors", [[0.8, 0.55, 1.0], [1.0, 0.6, 0.9]]), np.float32)
        self.col = cols[r.integers(0, len(cols), n)]
        self.s = cfg.get("strength", 0.8)
        self.T = ctx.T

    def apply(self, f, t):
        u = t / self.T
        pos = self.base + self.amp * np.sin(TAU * (self.k * u + self.ph))
        b = 0.25 + 0.75 * (0.5 - 0.5 * np.cos(TAU * (self.bk * u + self.bph))) ** 2
        for (x, y), spr, c, bb in zip(pos, self.spr, self.col, b):
            stamp(f, spr, x, y, c * self.s * bb)


class ShootingStar:
    """A shooting star streaks across the sky. Positions are fractions of the
    width and of the sky's height, so one setting fits every screen shape."""

    def __init__(self, ctx, cfg):
        self.W, self.T = ctx.W, ctx.T
        self.sky = getattr(ctx, "sky_bottom", ctx.H * 0.3)
        self.events = cfg["events"]            # [time, x, y, angle°, length, seconds]
        self.width = ctx.px(cfg.get("width", 1.6))
        self.col = np.array(cfg.get("color", [0.95, 0.88, 1.0]), np.float32)
        self.s = cfg.get("strength", 1.5)
        self.H = ctx.H

    def apply(self, f, t):
        for t0, fx, fy, ang, ln, dur in self.events:
            dt = (t - t0) % self.T
            if dt >= dur:
                continue
            u = dt / dur
            a = math.radians(ang)
            L = ln * self.W
            x0, y0 = fx * self.W, fy * self.sky
            hx, hy = x0 + math.cos(a) * L * u, y0 + math.sin(a) * L * u
            tail = L * 0.45 * min(1, u * 3)
            fade = math.sin(math.pi * u) ** 0.6
            buf = np.zeros((self.H, self.W), np.uint8)
            n = 12
            for i in range(n):  # brighter towards the head
                p0 = (hx - math.cos(a) * tail * i / n, hy - math.sin(a) * tail * i / n)
                p1 = (hx - math.cos(a) * tail * (i + 1) / n, hy - math.sin(a) * tail * (i + 1) / n)
                cv2.line(buf, (int(p0[0] * 4), int(p0[1] * 4)), (int(p1[0] * 4), int(p1[1] * 4)),
                         int(255 * (1 - i / n) ** 1.5), max(1, int(round(self.width))), cv2.LINE_AA, 2)
            layer = buf.astype(np.float32) / 255
            layer = layer + blur(layer, self.width * 3) * 2
            f += layer[..., None] * self.col * self.s * fade


class Rain:
    """Fine rain falling in front of the scene."""

    def __init__(self, ctx, cfg):
        r = ctx.rng
        n = cfg.get("count", 300)
        self.W, self.H, self.T = ctx.W, ctx.H, ctx.T
        self.len = ctx.px(cfg.get("length", 30))
        self.x = r.uniform(-0.2, 1.1, n) * ctx.W
        self.ph = r.random(n)
        lo, hi = cfg.get("passes", [8, 12])    # times each drop falls per loop
        self.passes = r.integers(lo, hi + 1, n)
        self.slant = math.tan(math.radians(cfg.get("angle", 12)))
        self.op = r.uniform(0.4, 1.0, n) * cfg.get("opacity", 0.25)
        self.col = np.array(cfg.get("color", [0.8, 0.75, 1.0]), np.float32)
        self.w = max(1, int(round(ctx.px(cfg.get("width", 1)))))

    def apply(self, f, t):
        buf = np.zeros((self.H, self.W), np.uint8)
        span = self.H + self.len
        for x, ph, k, op in zip(self.x, self.ph, self.passes, self.op):
            y = ((ph + k * t / self.T) % 1.0) * span - self.len
            x1 = x + y * self.slant
            x0, y0 = x1 - self.len * self.slant, y - self.len
            cv2.line(buf, (int(x0 * 4), int(y0 * 4)), (int(x1 * 4), int(y * 4)),
                     int(255 * op), self.w, cv2.LINE_AA, 2)
        f += (buf.astype(np.float32) / 255)[..., None] * self.col


class Skyline:
    """Depth on the horizon: lit skyscrapers glow up one at a time, and the
    red aviation lights already on the towers blink. Brighten-only, so
    nothing ever leaves a dark spot."""

    def __init__(self, ctx, cfg):
        self.T, self.ctx = ctx.T, ctx
        lo = cfg.get("min_luma", 0.35)
        self.items = []
        for it in cfg.get("buildings", []):
            m = ctx.region_mask(it) * smoothstep(lo, lo + 0.15, ctx.luma) * ctx.free
            layer = ctx.base * m[..., None]
            bloom = blur(layer, ctx.px(cfg.get("bloom_radius", 6)))
            self.items.append(dict(layer=layer, bloom=bloom, at=it["at"],
                                   dur=it.get("seconds", 3.0),
                                   bb=bbox(blur(m, ctx.px(cfg.get("bloom_radius", 6)) * 2) > 0.002)))
        self.boost = cfg.get("boost", 0.8)
        self.bloom = cfg.get("bloom", 0.8)
        # aviation lights: the red lights already on the tower tops
        bc = cfg.get("beacons")
        self.beacons = bc
        if bc:
            self.beacon_pos = ctx.pts(bc["points"])
            self.spr = sprite_dot(ctx.px(bc.get("size", 2.5)))
            self.bcol = np.array(bc.get("color", [1.0, 0.15, 0.25]), np.float32)

    def apply(self, f, t):
        for it in self.items:
            dt = (t - it["at"]) % self.T
            if dt >= it["dur"] or it["bb"] is None:
                continue
            e = math.sin(math.pi * dt / it["dur"]) ** 2
            y0, y1, x0, x1 = it["bb"]
            f[y0:y1, x0:x1] += (it["layer"][y0:y1, x0:x1] * self.boost
                                + it["bloom"][y0:y1, x0:x1] * self.bloom) * e
        if self.beacons:
            per = self.beacons.get("period", 1.5)
            on = self.beacons.get("on", 0.35)
            u = (t % per) / on
            e = math.sin(math.pi * u) ** 2 if u < 1 else 0.0
            for x, y in self.beacon_pos:
                stamp(f, self.spr, x, y, self.bcol * e * self.beacons.get("strength", 1.2))


class CityWave:
    """A slow wave of light sweeps across the city: only the lights already
    in the photo get brighter as it passes, so nothing looks painted on."""

    def __init__(self, ctx, cfg):
        region = ctx.regions(cfg["regions"]) * ctx.free
        opened = cv2.morphologyEx(ctx.base, cv2.MORPH_OPEN, ellipse(ctx.px(cfg.get("size", 4))))
        own = np.clip(ctx.base - opened, 0, None) * blur(region, ctx.px(4))[..., None]
        self.bb = bbox(region, pad=int(ctx.px(10)))
        y0, y1, x0, x1 = self.bb
        self.own = own[y0:y1, x0:x1]
        self.x = np.arange(x0, x1, dtype=np.float32)
        self.W, self.T = ctx.W, ctx.T
        self.width = ctx.px(cfg.get("width", 260))
        self.waves = cfg.get("waves", 2)
        self.boost = cfg.get("boost", 1.2)
        self.bloom = cfg.get("bloom", 0.6)
        self.br = ctx.px(cfg.get("bloom_radius", 4))
        self.dir = 1 if cfg.get("direction", "right") == "right" else -1

    def apply(self, f, t):
        y0, y1, x0, x1 = self.bb
        span = self.W + 4 * self.width
        u = (self.waves * t / self.T) % 1.0
        c = -2 * self.width + u * span
        if self.dir < 0:
            c = self.W - c
        # each wave wraps around, so the crest is periodic over the loop
        d = np.minimum(np.abs(self.x - c), span - np.abs(self.x - c))
        g = np.exp(-(d / self.width) ** 2)[None, :, None]
        add = self.own * g * self.boost
        f[y0:y1, x0:x1] += add + blur(add, self.br) * self.bloom


class Haze:
    """Soft mist drifting low over the water and the city. Seamless: the
    mist texture tiles left to right and slides one tile per loop."""

    def __init__(self, ctx, cfg):
        r = ctx.rng
        top, bottom = ctx.px(cfg["top"]), ctx.px(cfg["bottom"])
        self.y0, self.y1 = int(top), int(math.ceil(bottom))
        h, W = self.y1 - self.y0, ctx.W
        tex = np.zeros((h, W), np.float32)
        for scale, amp in [(160, 1.0), (60, 0.5), (25, 0.25)]:
            sx = ctx.px(scale)
            n = r.random((h, W)).astype(np.float32)
            pad = int(sx * 3)
            n = np.pad(n, ((0, 0), (pad, pad)), mode="wrap")
            n = cv2.GaussianBlur(n, (0, 0), sigmaX=sx, sigmaY=sx * 0.35)[:, pad:pad + W]
            tex += amp * (n - n.mean()) / (n.std() + 1e-6)
        tex = smoothstep(cfg.get("threshold", -0.2), 1.6, tex)
        yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
        tex *= np.clip(np.sin(np.pi * yy), 0, 1) ** 1.5   # thickest in the middle of the band
        self.tex = tex
        self.free = ctx.free[self.y0:self.y1]
        self.col = np.array(cfg.get("color", [0.62, 0.45, 0.85]), np.float32)
        self.s = cfg.get("strength", 0.35)
        self.sign = 1 if cfg.get("direction", "right") == "right" else -1
        self.x = np.arange(W, dtype=np.float64)
        self.W, self.T = W, ctx.T

    def apply(self, f, t):
        s = -self.sign * self.W * t / self.T
        u = (self.x + s) % self.W
        i0 = np.floor(u).astype(np.int64)
        fr = (u - i0).astype(np.float32)[None, :]
        m = self.tex[:, i0] * (1 - fr) + self.tex[:, (i0 + 1) % self.W] * fr
        a = (m * self.s * self.free)[..., None]
        sub = f[self.y0:self.y1]
        f[self.y0:self.y1] = 1 - (1 - sub) * (1 - a * self.col)


# order matters: stars come off the sky before the clouds move, and the road
# tracer is set up before the moon and towers that sync to it
EFFECTS = [("stars", Stars), ("clouds", Clouds), ("traffic", Traffic), ("moon_glow", MoonGlow),
           ("window_lights", Lights), ("house_lights", Lights), ("bridge_neon", Neon),
           ("water", Water), ("sparkles", Sparkles), ("fireflies", Fireflies),
           ("shooting_star", ShootingStar), ("rain", Rain), ("skyline", Skyline),
           ("city_wave", CityWave), ("haze", Haze)]


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

def encode(ctx, fx, path, seconds, final, crop=None):
    n = int(round(seconds * ctx.fps))
    cx, cy, cw, ch = crop or (0, 0, ctx.W, ctx.H)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb48le",
           "-s", f"{cw}x{ch}", "-r", str(ctx.fps), "-i", "-",
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
        f = frame(ctx, fx, (i / ctx.fps) % ctx.T)[cy:cy + ch, cx:cx + cw]
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
               "bridge_neon": (1, 0.1, 0.4), "traffic": (1, 1, 0), "water": (0.2, 0.4, 1),
               "sparkles": (1, 0.9, 1), "fireflies": (0.9, 0.5, 1)}
    for key, e in fx:
        if key not in colours:
            continue
        c = np.array(colours[key], np.float32)
        if isinstance(e, (Stars, Lights)):
            m = (e.labels > 0).astype(np.float32)
        elif isinstance(e, Clouds):
            m = np.zeros((ctx.H, ctx.W), np.float32)
            m[:e.rows] = e.m[..., 0] * 0.35
        elif isinstance(e, Sparkles):
            m = np.zeros((ctx.H, ctx.W), np.float32)
            for x, y in e.pos:
                stamp(m[..., None], e.spr, x, y, np.ones(1, np.float32))
        elif isinstance(e, Fireflies):
            m = np.zeros((ctx.H, ctx.W), np.float32)
            for (x, y), spr in zip(e.base, e.spr):
                stamp(m[..., None], spr, x, y, np.ones(1, np.float32))
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
        m = np.clip(m, 0, 1)
        over = over * (1 - m[..., None]) + c * m[..., None]
        cv2.imwrite(os.path.join(outdir, f"{key}.png"), (m * 255).astype(np.uint8))
    over = over * (1 - ctx.protect[..., None] * 0.6) + np.array([1, 0, 0]) * ctx.protect[..., None] * 0.6
    cv2.imwrite(os.path.join(outdir, "_overview.jpg"),
                cv2.cvtColor((np.clip(over, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))


def merge(dst, src):
    """Layer a variant over a scene: nested settings merge, `null` removes."""
    for k, v in src.items():
        if v is None:
            dst.pop(k, None)
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--preview", action="store_true", help="small H.264 preview")
    g.add_argument("--final", action="store_true", help="native-resolution HEVC loop per screen")
    g.add_argument("--masks", action="store_true", help="write effect masks to masks/<scene>/")
    g.add_argument("--still", type=float, metavar="SECONDS", help="one frame as PNG")
    ap.add_argument("--seconds", type=float, help="preview length (default: whole loop)")
    ap.add_argument("--variant", help="a scenes/variants/*.yml file layered on top of the scene")
    ap.add_argument("--closeup", metavar="X,Y,W,H",
                    help="with --preview: a 1:1 crop of the first screen at its real size")
    a = ap.parse_args()

    with open(a.scene) as fh:
        scene = yaml.safe_load(fh)
    stem = os.path.splitext(os.path.basename(a.scene))[0]
    if a.variant:
        with open(a.variant) as fh:
            merge(scene, yaml.safe_load(fh) or {})
        stem += "__" + os.path.splitext(os.path.basename(a.variant))[0]
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

    if a.closeup and a.preview:
        ctx, fx = build(scene, tuple(scene["outputs"][0]["size"]))
        crop = tuple(int(v) for v in a.closeup.split(","))
        os.makedirs(os.path.join(ROOT, "previews"), exist_ok=True)
        path = os.path.join(ROOT, "previews", f"{stem}_closeup.mp4")
        print(path)
        encode(ctx, fx, path, a.seconds or ctx.T, final=False, crop=crop)
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
