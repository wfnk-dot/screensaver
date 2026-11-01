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

`loops/frog-meadow_newtab-ultrawide.mp4` (3440 × 1440, H.264): the
Discord/Notion banner video, untouched, with the rest of the picture added
round it (more sky, the frog's feet and the grass below, more tree on the
right). The added sky moves with the banner's clouds. How it's made:
`tools/banner-extend/README.md`.
