# Screensaver: hand-animated wallpapers, one loop per screen

Wyn has a separately edited version of his night-city wallpaper for each monitor (e.g. the widescreen version has the moon moved closer). This is **not** an auto-crop of one image.

**Goal:** animate each version by hand, the same way his Discord banner and profile picture were animated:
- clouds drifting
- neon signs and road neon flickering
- building lights twinkling
- any text glowing/looping in neon

Then play the right loop on the right screen as his macOS screensaver.

The build has two parts:
- **Part 1 (cloud session, free credit):** animate each image into a seamless looping video, with Wyn approving each one. Push to `wfnk-dot/screensaver`.
- **Part 2 (short local session on the Mac):** a tiny `.saver` that plays the correct loop on each screen.

The first set of loops is Wyn's current night-city wallpaper, but the tool is generic: any wallpaper can be animated and added later. Name loop files by wallpaper and screen, e.g. `night-city_widescreen.mp4`.

---

## Hard rules

- **Wyn decides what moves.** For each image, first send him a short numbered list of proposed effects, e.g. "1. clouds drift left, 2. neon sign on the road flickers, 3. window lights twinkle, 4. moon glow pulses". He ticks, edits or adds. Only then render.
- **Seamless loops.** No visible jump when the video restarts. Every effect is periodic over the loop length, or crossfaded.
- **Subtle and clean.** Purple/blue vibe, no orange, nothing busy. Match the feel of his animated Discord banner. Ask him for it as a style reference.
- **Exact resolution per screen.** Each loop is rendered at that monitor's native resolution, so it stays sharp.
- **Light.** Encode as HEVC (H.265), which Apple Silicon decodes in hardware, at 30 fps, about 20–30s loops. Playback must be near-zero CPU.
- **If something fails twice, stop** and explain the options in plain language.
- **Mouse only.** No keyboard shortcuts.
- **Wyn isn't a developer.** Install is a double-click.

---

## Inputs from Wyn (attach to the Part 1 session)

1. **One image per screen:** the edited versions he uses now. Label which is the widescreen, the 27", the Arzopa and the MacBook (if different).
2. **His Discord banner (animated)** as the style reference for how motion should feel.
3. **Native resolution of each screen** (System Settings → Displays). If he doesn't know, ask him to screenshot that page.

---

## Part 1 (cloud): animate each image

For each image:

1. **Study the image and propose effects** (numbered list, sent to Wyn). Typical options:
   - **Clouds / sky drift:** separate the sky layer, slowly translate it with a seamless wrap or soft displacement, and fill behind it cleanly (inpaint or mirror) so no hole appears.
   - **Neon flicker:** mask each neon element (signs, road neon, outlines). Animate brightness with an occasional realistic flicker, plus a soft bloom.
   - **Text neon loop:** if the image has text, do a glow pulse or a "tube lighting up" sweep along the letters.
   - **Window lights:** a few windows fading on/off at different times.
   - **Moon / sky glow:** a slow breathing glow.
   - **Rain / haze / light particles:** optional, very light.
   - **Light trails on roads:** optional, if the image has roads.
2. **Build the effect masks** for this image (hand-placed regions are fine; Claude can look at the image). Save them in the repo so the same image can be re-rendered later with tweaks.
3. **Render a short preview** (5–10s, smaller size) and send it to Wyn. Iterate on his feedback.
4. **Render the final seamless loop** at native resolution: HEVC .mp4, 30 fps.
5. Repeat for each screen's image.

**Tools:** Python (numpy, OpenCV, Pillow) + ffmpeg in the cloud box. Keep the per-image effect setup in a readable config (`scenes/<name>.yml`: effects, masks, speeds), so future images follow the same process.

**Later, a new wallpaper** means a new short cloud session using the same pipeline: attach images → approve effects → get loops. Write `HOW-TO-ADD-A-NEW-WALLPAPER.md` with the exact message to send.

---

## Part 2 (local, in `~/Documents/screensaver`): the screensaver

1. Clone the repo and build `Screensaver.saver`: a `ScreenSaverView` that plays a looping video with `AVPlayerLooper` + `AVPlayerLayer`, muted and aspect-fill.
2. **Per-screen assignment:** each screen instance picks its video by display name/resolution. Default mapping comes from the Part 1 labels.
3. **Options panel:**
   - For each connected screen, a dropdown of the loop videos in the saver's folder, plus "Black" and "Same as main".
   - An "Open videos folder" button, so new loops can be dropped in.
4. **Clean shutdown:** stop and release the players on `stopAnimation` and on `com.apple.screensaver.willstop`. Confirm in Activity Monitor that `legacyScreenSaver` drops to ~0% after waking. This is a known macOS problem.
5. `Install Screensaver.command`: builds, copies to `~/Library/Screen Savers/` and opens Screen Saver settings.
6. **Test:** the right loop on each screen, no visible loop seam, low CPU while running, and nothing left running after wake.

---

## Out of scope

Don't build any of these:
- Live data
- Sound
- Desktop wallpaper mode
- Auto-detecting effects without Wyn's approval
- An iPhone version
