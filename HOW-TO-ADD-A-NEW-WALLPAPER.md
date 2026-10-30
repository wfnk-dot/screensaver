# How to add a new wallpaper

1. Upload the wallpaper images to this repo on github.com
   (**Add file → Upload files**, drag them in, **Commit changes**).
   Upload one edited version per screen shape.
2. Start a new Claude Code session on the web with the `wfnk-dot/screensaver`
   repo selected, and send this message (fill in the blanks):

   > Read `HOW-TO-ADD-A-NEW-WALLPAPER.md` and `tools/render.py` in this repo.
   > Add a new wallpaper called **____**.
   > I uploaded: **____** (widescreen, 3440 × 1440) and **____** (27" 2560 × 1440 and Arzopa 1920 × 1080).
   > Follow the same process as night-city: move the files into `sources/`,
   > send me a numbered list of proposed effects for each image, wait for my
   > ticks, then build `scenes/<name>_<shape>.yml`, send me the previews, and
   > only after I approve render the final loops into `loops/` and push.

3. Tick, edit or add to the list of effects Claude sends back.
4. Watch the previews and say what to change.
5. When you approve, the final loops land in the `loops/` folder, named
   `<wallpaper>_<screen>.mp4`. Drop them in the screensaver's videos folder.

## For Claude: how the pipeline works

- `scenes/<name>_<shape>.yml` describes one edited image: its source file, the
  screens it's rendered for (`outputs`), the areas never animated (`protect`)
  and each effect with its hand-placed regions. Coordinates are pixels on the
  `ref_size` grid and get scaled to any render size.
- `python3 tools/render.py <scene> --masks` writes `masks/<scene>/`, including
  `_overview.jpg` (red = protected). Look at it after placing regions.
- `--still <seconds>` writes one frame. `--preview --closeup X,Y,W,H` writes a
  1:1 crop at the screen's real size, which is how detail must be judged. `--preview` writes a 1280-px H.264
  loop to `previews/`. `--final` writes a native-resolution HEVC Main10 loop per
  output to `loops/` (30 fps, `hvc1` tag so macOS plays it).
- Every effect uses whole cycles per `loop_seconds`, so the loop is seamless;
  the renderer prints the seam error (it should be ~1e-5).
- Effects available: `stars`, `clouds`, `moon_glow`, `window_lights`,
  `house_lights` (both use the Lights effect: `mode: fade` or `twinkle`),
  `bridge_neon` (any neon structure, traced with `lines`), `traffic` (pulses
  along a road `points` path; `mode: tracer` is one neon light running the
  road, recoloured to a saturated `neon_color` so it never washes to white;
  the moon and towers can sync to it), `water`, `sparkles`, `fireflies`,
  `shooting_star` and `rain`; `clouds` also takes `lightning`. Send Wyn
  several variants (`scenes/variants/`) rather than one. Wyn's taste so far:
  vivid over subtle, colours that belong to the image, no white flashes,
  no rain or shooting stars. Masks must sit exactly on what they animate:
  trace roads at full resolution (`fill: true` lights the road's whole lit
  width) and check `masks/` at full size; if something is too small to place
  precisely (e.g. single windows), leave it out rather than guess. Never
  repaint real pixels with a flat colour (it looks like a bad filter):
  brighten the photo's own light instead (`neon_color: lift`).
- Style reference: `references/discord-banner.mp4`. What it does: clouds move
  only where they cover nothing; small soft particles in the image's own two
  colours fade in and out in the empty corners; a short light travels along
  outlines; everything else is still. Nothing flashes, nothing turns white. Add a new effect class in
  `tools/render.py` and list it in `EFFECTS` when an image needs something new.
- Needs: `pip install opencv-python-headless numpy scipy pyyaml`, and ffmpeg with libx265.
