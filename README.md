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
road light, the moon flare and the tower flashes line up on all three
screens. For Part 2: start each screen's player at
`(current time) mod 30s` so the screens stay in step with each other.

## Trying variations

`scenes/variants/*.yml` are extras layered on top of a scene, e.g.
`python3 tools/render.py scenes/night-city_widescreen.yml --variant scenes/variants/neon-tube.yml --preview`.
