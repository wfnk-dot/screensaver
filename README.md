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

The Discord/Notion banner, made for the ultrawide new tab: same frog size,
same neon boxes in the same places, same sky band; a little more meadow at the
bottom so it fills 3440 × 1440 without cutting the boxes off.

| File | Use it for |
| --- | --- |
| `loops/frog-meadow_newtab-ultrawide.mp4` | Brave new tab on the ultrawide (H.264) |
| `loops/frog-meadow_widescreen.mp4` | Mac screensaver, main screen (HEVC) |

- `sources/frog-meadow_banner-layout.png`: the banner's background rebuilt at full
  quality (sky band joined onto the meadow, as the banner does), no text, no frog.
- `sources/frog-meadow.png`: the whole clean background it's cut from.
- `sources/frog-meadow_frog.png`: the frog, redrawn sharp, no purple outline.
- The neon boxes are drawn by the renderer (`neon_boxes`, Marcellus font), placed
  by measuring the banner. Two lights run round each box every 4 s, in step.
- Loops are 8 seconds.
