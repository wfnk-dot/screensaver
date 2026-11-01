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

## Frog meadow (new tab, Discord, Notion)

The purple frog scene with the neon "Fuck bitches / Get Money." boxes. One
master picture; every version is a crop of it, so they always match.

| File | Use it for |
| --- | --- |
| `loops/frog-meadow_newtab-ultrawide.mp4` | Brave new tab on the ultrawide (3440 × 1440) |
| `loops/frog-meadow_newtab-16x9.mp4` | Brave new tab on a normal screen (2560 × 1440) |
| `loops/frog-meadow_banner.gif` | Discord profile banner, Notion cover (960 × 340) |
| `loops/frog-meadow_banner-hd.mp4` | Same banner, twice the size, as a video |
| `loops/frog-meadow__dont-be_banner.gif` | Notion "Trades" cover ("Don't be / a cunt.") |
| `loops/frog-meadow_widescreen.mp4`, `_27in`, `_arzopa` | Mac screensaver screens |

What's in it:
- `sources/frog-meadow.png`: the clean background (no text, no frog). Built from
  the purple still (middle) and the widened new-tab video (sides), with the old
  text removed by AI fill.
- `sources/frog-meadow_frog.png`: the frog, redrawn sharp from the original green
  picture (`sources/frog-meadow_original-green.jpg`): smooth outline, flat colours,
  lilac edge glow.
- The neon boxes are drawn by the renderer (`neon_boxes` effect) in Marcellus
  (`fonts/`), so they're sharp at any size. Both boxes run the same two lights
  round their outline at the same moment: always in sync.
- Loops are 8 seconds (start each screen at `(current time) mod 8 s`).

**New words** (e.g. another Notion page): copy `scenes/variants/dont-be.yml`,
change the two `text:` lines, and run
`python3 tools/render.py scenes/frog-meadow.yml --variant scenes/variants/<name>.yml --final`.
