import AVFoundation
import AppKit
import ScreenSaver

// Plays one seamless loop per screen. Each screen picks its video from the
// options panel (keyed by the screen's name), falling back to a default
// chosen by the screen's resolution. All screens start at (now mod loop
// length) so the loops stay in step with each other.

let moduleName = "com.wfnk.screensaver"
let choiceBlack = "Black"
let choiceSameAsMain = "Same as main"

// Default mapping from the README: native pixel size -> loop name suffix.
let defaultLoopForSize: [String: String] = [
    "3440x1440": "_widescreen",
    "2560x1440": "_27in",
    "1920x1080": "_arzopa",
]

enum Videos {
    /// The real home folder. NSHomeDirectory() points inside the sandbox
    /// container when running in legacyScreenSaver.
    static var realHome: URL {
        if let pw = getpwuid(getuid()), let dir = pw.pointee.pw_dir {
            return URL(fileURLWithPath: String(cString: dir))
        }
        return URL(fileURLWithPath: NSHomeDirectory())
    }

    /// Where new loops are dropped in.
    static var folder: URL {
        realHome.appendingPathComponent("Library/Screen Savers/Screensaver Videos", isDirectory: true)
    }

    /// Copies shipped inside the saver, used if the folder above can't be read.
    static var bundled: URL? {
        Bundle(for: LoopSaverView.self).resourceURL?.appendingPathComponent("Videos", isDirectory: true)
    }

    /// All loop videos, by file name. The videos folder wins over bundled copies.
    static func all() -> [String: URL] {
        var found: [String: URL] = [:]
        for dir in [bundled, folder].compactMap({ $0 }) {
            let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
            for url in files where ["mp4", "mov", "m4v"].contains(url.pathExtension.lowercased()) {
                found[url.lastPathComponent] = url
            }
        }
        return found
    }

    static func names() -> [String] {
        all().keys.sorted { $0.localizedStandardCompare($1) == .orderedAscending }
    }
}

enum Settings {
    static var defaults: ScreenSaverDefaults? {
        ScreenSaverDefaults(forModuleWithName: moduleName)
    }

    static func key(for screen: NSScreen) -> String {
        "video." + screen.localizedName
    }

    static func pixelSize(of screen: NSScreen) -> String {
        let scale = screen.backingScaleFactor
        let w = Int((screen.frame.width * scale).rounded())
        let h = Int((screen.frame.height * scale).rounded())
        return "\(w)x\(h)"
    }

    /// The video picked for a screen if nothing was chosen in the options panel.
    static func defaultChoice(for screen: NSScreen) -> String {
        let names = Videos.names()
        if let suffix = defaultLoopForSize[pixelSize(of: screen)] {
            // Prefer night-city, the first wallpaper, then any other match.
            let matches = names.filter { ($0 as NSString).deletingPathExtension.hasSuffix(suffix) }
            if let pick = matches.first(where: { $0.hasPrefix("night-city") }) ?? matches.first {
                return pick
            }
        }
        if screen == NSScreen.screens.first { return names.first ?? choiceBlack }
        return choiceSameAsMain
    }

    static func choice(for screen: NSScreen) -> String {
        defaults?.string(forKey: key(for: screen)) ?? defaultChoice(for: screen)
    }

    static func setChoice(_ value: String, for screen: NSScreen) {
        defaults?.set(value, forKey: key(for: screen))
    }

    /// The video file to play on a screen, or nil for black.
    static func videoURL(for screen: NSScreen?) -> URL? {
        let main = NSScreen.screens.first
        let target = screen ?? main
        guard let target else { return nil }
        var name = choice(for: target)
        if name == choiceSameAsMain, let main, main != target {
            name = choice(for: main)
        }
        return Videos.all()[name]
    }
}

@objc(LoopSaverView)
final class LoopSaverView: ScreenSaverView {
    private var player: AVQueuePlayer?
    private var looper: AVPlayerLooper?
    private var playerLayer: AVPlayerLayer?
    private var stopObserver: NSObjectProtocol?
    private var configWindow: NSWindow?
    private var popups: [(NSScreen, NSPopUpButton)] = []

    override init?(frame: NSRect, isPreview: Bool) {
        super.init(frame: frame, isPreview: isPreview)
        wantsLayer = true
        layer?.backgroundColor = NSColor.black.cgColor
        animationTimeInterval = 1.0  // AVFoundation does the drawing; no per-frame work here.

        // macOS often leaves the screensaver process running after wake.
        // Tear down on its "will stop" notice and quit so nothing lingers.
        stopObserver = DistributedNotificationCenter.default().addObserver(
            forName: NSNotification.Name("com.apple.screensaver.willstop"), object: nil, queue: .main
        ) { [weak self] _ in
            guard let self else { return }
            self.stopPlayback()
            if !self.isPreview {
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { exit(0) }
            }
        }
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
    }

    deinit {
        if let stopObserver { DistributedNotificationCenter.default().removeObserver(stopObserver) }
    }

    override func draw(_ rect: NSRect) {
        NSColor.black.setFill()
        rect.fill()
    }

    override func animateOneFrame() {}

    override func startAnimation() {
        super.startAnimation()
        startPlayback()
    }

    override func stopAnimation() {
        stopPlayback()
        super.stopAnimation()
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        // The screen is known only once the view is in its window.
        if isAnimating, window != nil, player == nil { startPlayback() }
    }

    private func startPlayback() {
        stopPlayback()
        guard let url = Settings.videoURL(for: window?.screen) else { return }

        let asset = AVURLAsset(url: url)
        let item = AVPlayerItem(asset: asset)
        let queue = AVQueuePlayer()
        queue.isMuted = true
        queue.preventsDisplaySleepDuringVideoPlayback = false
        let looper = AVPlayerLooper(player: queue, templateItem: item)

        let layer = AVPlayerLayer(player: queue)
        layer.videoGravity = .resizeAspectFill
        layer.frame = bounds
        layer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        layer.backgroundColor = NSColor.black.cgColor
        self.layer?.addSublayer(layer)

        player = queue
        self.looper = looper
        playerLayer = layer

        // Start every screen at the same point of the shared 30 s clock.
        Task { @MainActor [weak self] in
            var length = 30.0
            if let d = try? await asset.load(.duration), d.seconds.isFinite, d.seconds > 0 {
                length = d.seconds
            }
            guard let self, self.player === queue else { return }
            // Synchronized start is only allowed once the player is ready.
            for _ in 0..<150 where queue.status != .readyToPlay {
                try? await Task.sleep(nanoseconds: 20_000_000)
            }
            guard self.player === queue else { return }
            guard queue.status == .readyToPlay else {
                let offset = fmod(Date().timeIntervalSince1970, length)
                await queue.seek(to: CMTime(seconds: offset, preferredTimescale: 600))
                if self.player === queue { queue.play() }
                return
            }
            // Seek a little ahead, then start exactly when the clock gets there.
            let lead = 0.5
            let startDate = Date().timeIntervalSince1970 + lead
            let offset = CMTime(seconds: fmod(startDate, length), preferredTimescale: 600)
            await queue.seek(to: offset, toleranceBefore: .zero, toleranceAfter: .zero)
            guard self.player === queue else { return }
            let remaining = max(0, startDate - Date().timeIntervalSince1970)
            let hostStart = CMTimeAdd(CMClockGetTime(CMClockGetHostTimeClock()),
                                      CMTime(seconds: remaining, preferredTimescale: 1_000_000_000))
            queue.automaticallyWaitsToMinimizeStalling = false
            queue.setRate(1, time: remaining > 0 ? offset : .invalid, atHostTime: remaining > 0 ? hostStart : .invalid)
        }
    }

    private func stopPlayback() {
        looper?.disableLooping()
        player?.pause()
        player?.removeAllItems()
        playerLayer?.player = nil
        playerLayer?.removeFromSuperlayer()
        looper = nil
        player = nil
        playerLayer = nil
    }

    // MARK: - Options panel

    override var hasConfigureSheet: Bool { true }

    override var configureSheet: NSWindow? {
        let window = makeConfigWindow()
        configWindow = window
        return window
    }

    private func makeConfigWindow() -> NSWindow {
        let names = Videos.names()
        let screens = NSScreen.screens
        let rowHeight: CGFloat = 32
        let width: CGFloat = 520
        let height: CGFloat = 110 + CGFloat(screens.count) * rowHeight + 50

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: width, height: height),
                              styleMask: [.titled], backing: .buffered, defer: false)
        let content = NSView(frame: NSRect(x: 0, y: 0, width: width, height: height))
        window.contentView = content

        let title = NSTextField(labelWithString: "Which loop plays on each screen")
        title.font = .boldSystemFont(ofSize: 13)
        title.frame = NSRect(x: 20, y: height - 40, width: width - 40, height: 20)
        content.addSubview(title)

        popups = []
        var y = height - 80
        for (index, screen) in screens.enumerated() {
            let label = NSTextField(labelWithString: screen.localizedName + (index == 0 ? " (main)" : ""))
            label.frame = NSRect(x: 20, y: y + 4, width: 190, height: 20)
            label.lineBreakMode = .byTruncatingTail
            label.toolTip = Settings.pixelSize(of: screen)
            content.addSubview(label)

            let popup = NSPopUpButton(frame: NSRect(x: 215, y: y, width: width - 235, height: 26), pullsDown: false)
            popup.addItems(withTitles: names)
            if !names.isEmpty { popup.menu?.addItem(.separator()) }
            popup.addItem(withTitle: choiceBlack)
            if index != 0 { popup.addItem(withTitle: choiceSameAsMain) }
            let current = Settings.choice(for: screen)
            if popup.itemTitles.contains(current) {
                popup.selectItem(withTitle: current)
            } else {
                popup.selectItem(withTitle: index == 0 ? choiceBlack : choiceSameAsMain)
            }
            content.addSubview(popup)
            popups.append((screen, popup))
            y -= rowHeight
        }

        if names.isEmpty {
            let note = NSTextField(labelWithString: "No videos found. Put .mp4 loops in the videos folder.")
            note.textColor = .secondaryLabelColor
            note.frame = NSRect(x: 20, y: y + 4, width: width - 40, height: 20)
            content.addSubview(note)
        }

        let open = NSButton(title: "Open videos folder", target: self, action: #selector(openVideosFolder))
        open.bezelStyle = .rounded
        open.frame = NSRect(x: 14, y: 14, width: 170, height: 32)
        content.addSubview(open)

        let cancel = NSButton(title: "Cancel", target: self, action: #selector(cancelConfig))
        cancel.bezelStyle = .rounded
        cancel.frame = NSRect(x: width - 200, y: 14, width: 90, height: 32)
        content.addSubview(cancel)

        let ok = NSButton(title: "OK", target: self, action: #selector(saveConfig))
        ok.bezelStyle = .rounded
        ok.keyEquivalent = "\r"
        ok.frame = NSRect(x: width - 104, y: 14, width: 90, height: 32)
        content.addSubview(ok)

        return window
    }

    @objc private func openVideosFolder() {
        let folder = Videos.folder
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        if !NSWorkspace.shared.open(folder) {
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: folder.path)
        }
    }

    @objc private func cancelConfig() {
        closeConfig()
    }

    @objc private func saveConfig() {
        for (screen, popup) in popups {
            if let title = popup.titleOfSelectedItem {
                Settings.setChoice(title, for: screen)
            }
        }
        Settings.defaults?.synchronize()
        closeConfig()
        if isAnimating { startPlayback() }
    }

    private func closeConfig() {
        guard let window = configWindow else { return }
        if let parent = window.sheetParent {
            parent.endSheet(window)
        } else {
            window.close()
        }
        configWindow = nil
        popups = []
    }
}
