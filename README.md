# Screensaver

Hand-animated wallpapers, one seamless loop per screen, played by a macOS screensaver.

| Folder | What's in it |
| --- | --- |
| `sources/` | The edited wallpaper images, one per screen shape |
| `scenes/` | Which effects each image gets, and where |
| `masks/` | Pictures of every effect's area, for checking (`_overview.jpg`) |
| `previews/` | Small preview loops for approval |
| `loops/` | The final loops, e.g. `night-city_widescreen.mp4` |
| `tools/render.py` | The renderer |

Screens: widescreen 3440 × 1440, 27" 2560 × 1440, Arzopa 1920 × 1080.

Adding another wallpaper: see [HOW-TO-ADD-A-NEW-WALLPAPER.md](HOW-TO-ADD-A-NEW-WALLPAPER.md).

## Timing

Every loop is 30 seconds and every effect runs on the same clock, so the
road light and the moon swell line up on all three screens. For Part 2: start each screen's player at
`(current time) mod 30s` so the screens stay in step with each other.

## Trying variations

Put extras in `scenes/variants/<name>.yml` and layer them on a scene with
`--variant scenes/variants/<name>.yml`.

## Part 2: the screensaver (on the Mac)

The spec is in [SCREENSAVER-SPEC.md](SCREENSAVER-SPEC.md). Part 1 (the loops)
is done; Part 2 is built in a short Claude Code session on the Mac.

Default mapping for the screensaver:

| Screen | Native resolution | Loop |
| --- | --- | --- |
| Widescreen (main) | 3440 × 1440 | `loops/night-city_widescreen.mp4` |
| 27" | 2560 × 1440 | `loops/night-city_27in.mp4` |
| Arzopa | 1920 × 1080 | `loops/night-city_arzopa.mp4` |

The MacBook is ignored (it's used through Universal Control). All loops are
30 s; start each screen at `(current time) mod 30 s` so they stay in step.

## Frog meadow (new tab)

The Discord/Notion banner, uncropped: the same frog size, the same neon boxes
in the same places, with the full picture around them. (The banners themselves
are left as they are; they join the sky on top of the meadow to fit, so they
aren't a plain crop.)

| File | Use it for |
| --- | --- |
| `loops/frog-meadow_newtab-ultrawide.mp4` | Brave new tab on the ultrawide (3440 × 1440) |
| `loops/frog-meadow_newtab-16x9.mp4` | Brave new tab on a normal screen (2560 × 1440) |
| `loops/frog-meadow_full.mp4` | The whole picture at its original shape (3024 × 1964) |
| `loops/frog-meadow_widescreen.mp4`, `_27in`, `_arzopa` | Mac screensaver screens |

What's in it:
- `sources/frog-meadow.png`: the clean background (no text, no frog): the purple
  still in the middle and the widened new-tab video at the sides, old text removed.
- `sources/frog-meadow_frog.png`: the frog, redrawn sharp from the original green
  picture, no purple outline. Placed at the banner's size (1.3×) and position.
- The neon boxes are drawn by the renderer (`neon_boxes`, Marcellus font in
  `fonts/`), sized and placed by measuring the banner. Two lights run clockwise
  round each box once every 4 s, in step on both boxes, like the banner.
- Loops are 8 seconds.
