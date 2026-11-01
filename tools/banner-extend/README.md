# Banner extend

Makes the frog new-tab video by **extending the Discord/Notion banner video**
(`references/frog-banner_synced.mp4`), not by redrawing anything: the banner
plays untouched in the middle (only its outer few pixels are softened into the
surroundings), and the missing picture around it comes from the full image
(`sources/frog-meadow.png`, the clean background; the original frog is taken
from the purple still and scaled 1.3× exactly as the banner has it).

- The banner joins a sky band (from higher up the picture, scale 2.14) onto the
  meadow (scale 2.3235, 1 banner px = 2.3235 px of the 3104 × 1299 picture).
  The extension uses the same two mappings and the same join (banner rows 106–124).
- The added sky moves with the banner's clouds: the cloud motion is measured
  in every banner frame (optical flow) and carried out into the new sky.
- Stars twinkle and a few fireflies drift in the added parts.
- Canvas: 1092 × 457 banner px (banner at 66, 53), scaled to 3440 × 1440,
  32 s at 25 fps like the banner.

Scripts (run in order, from a working folder holding the intermediate files):
`extend.py` (static surroundings), `seam.py` (colour match + soft join),
`render_ext.py full <out.mp4>`.
