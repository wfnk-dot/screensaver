import AVFoundation
import AppKit
import ServiceManagement

// Moving wallpaper: plays one seamless loop behind the desktop icons on each
// screen, using the same loops and the same 30 s clock as the screensaver.
// Each screen pauses whenever it's fully covered, asleep, locked or showing
// the screensaver, so it costs nothing while it can't be seen.

let videosFolder = URL(fileURLWithPath: NSHomeDirectory())
    .appendingPathComponent("Library/Screen Savers/Screensaver Videos", isDirectory: true)

// Default mapping from the README: native pixel size -> loop name suffix.
let loopForSize: [String: String] = [
    "3440x1440": "_widescreen",
    "2560x1440": "_27in",
    "1920x1080": "_arzopa",
]

func pixelSize(of screen: NSScreen) -> String {
    let scale = screen.backingScaleFactor
    return "\(Int((screen.frame.width * scale).rounded()))x\(Int((screen.frame.height * scale).rounded()))"
}

func videoURL(for screen: NSScreen) -> URL? {
    let files = ((try? FileManager.default.contentsOfDirectory(at: videosFolder, includingPropertiesForKeys: nil)) ?? [])
        .filter { ["mp4", "mov", "m4v"].contains($0.pathExtension.lowercased()) }
        .sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    guard let suffix = loopForSize[pixelSize(of: screen)] else { return nil }
    let matches = files.filter { $0.deletingPathExtension().lastPathComponent.hasSuffix(suffix) }
    return matches.first { $0.lastPathComponent.hasPrefix("night-city") } ?? matches.first
}

/// One borderless window at desktop level on one screen, playing its loop.
final class WallpaperWindow: NSWindow {
    private let player = AVQueuePlayer()
    private var looper: AVPlayerLooper?
    private var loopLength = 30.0
    private(set) var isPlaying = false

    init(screen: NSScreen, video: URL) {
        super.init(contentRect: screen.frame, styleMask: .borderless, backing: .buffered, defer: false)
        setFrame(screen.frame, display: false)
        level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopWindow)))
        collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle, .fullScreenNone]
        ignoresMouseEvents = true
        isOpaque = true
        hasShadow = false
        backgroundColor = .black
        isReleasedWhenClosed = false

        let view = NSView(frame: NSRect(origin: .zero, size: screen.frame.size))
        view.wantsLayer = true
        let layer = AVPlayerLayer(player: player)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        layer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        view.layer?.addSublayer(layer)
        contentView = view

        player.isMuted = true
        player.preventsDisplaySleepDuringVideoPlayback = false
        player.automaticallyWaitsToMinimizeStalling = false
        let asset = AVURLAsset(url: video)
        looper = AVPlayerLooper(player: player, templateItem: AVPlayerItem(asset: asset))
        Task { @MainActor in
            if let d = try? await asset.load(.duration), d.seconds.isFinite, d.seconds > 0 {
                self.loopLength = d.seconds
            }
        }
    }

    /// Start (or resume) in step with the shared clock: (now mod loop length).
    func play() {
        guard !isPlaying else { return }
        isPlaying = true
        NSLog("Wallpaper: playing on %@", screen?.localizedName ?? "?")
        Task { @MainActor in
            for _ in 0..<150 where player.status != .readyToPlay {
                try? await Task.sleep(nanoseconds: 20_000_000)
            }
            guard isPlaying else { return }
            let startDate = Date().timeIntervalSince1970 + 0.3
            let offset = CMTime(seconds: fmod(startDate, loopLength), preferredTimescale: 600)
            await player.seek(to: offset, toleranceBefore: .zero, toleranceAfter: .zero)
            guard isPlaying else { return }
            let remaining = startDate - Date().timeIntervalSince1970
            if player.status == .readyToPlay, remaining > 0 {
                let host = CMTimeAdd(CMClockGetTime(CMClockGetHostTimeClock()),
                                     CMTime(seconds: remaining, preferredTimescale: 1_000_000_000))
                player.setRate(1, time: offset, atHostTime: host)
            } else {
                player.play()
            }
        }
    }

    func pause() {
        if isPlaying { NSLog("Wallpaper: paused on %@", screen?.localizedName ?? "?") }
        isPlaying = false
        player.pause()
    }

    func tearDown() {
        pause()
        looper?.disableLooping()
        looper = nil
        player.removeAllItems()
        close()
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var windows: [WallpaperWindow] = []
    private var statusItem: NSStatusItem?
    private var screensAsleep = false
    private var screensaverOn = false
    private var locked = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        try? SMAppService.mainApp.register()  // start at login
        setUpMenu()
        buildWindows()

        let nc = NotificationCenter.default
        nc.addObserver(self, selector: #selector(screensChanged),
                       name: NSApplication.didChangeScreenParametersNotification, object: nil)
        nc.addObserver(self, selector: #selector(updatePlayback),
                       name: NSWindow.didChangeOcclusionStateNotification, object: nil)

        let ws = NSWorkspace.shared.notificationCenter
        ws.addObserver(forName: NSWorkspace.screensDidSleepNotification, object: nil, queue: .main) { [weak self] _ in
            self?.screensAsleep = true; self?.updatePlayback()
        }
        ws.addObserver(forName: NSWorkspace.screensDidWakeNotification, object: nil, queue: .main) { [weak self] _ in
            self?.screensAsleep = false; self?.updatePlayback()
        }

        let dnc = DistributedNotificationCenter.default()
        let events: [(String, (AppDelegate) -> Void)] = [
            ("com.apple.screensaver.didstart", { $0.screensaverOn = true }),
            ("com.apple.screensaver.didstop", { $0.screensaverOn = false }),
            ("com.apple.screenIsLocked", { $0.locked = true }),
            ("com.apple.screenIsUnlocked", { $0.locked = false }),
        ]
        for (name, change) in events {
            dnc.addObserver(forName: NSNotification.Name(name), object: nil, queue: .main) { [weak self] _ in
                guard let self else { return }
                change(self)
                self.updatePlayback()
            }
        }
    }

    private func setUpMenu() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "moon.stars", accessibilityDescription: "Wallpaper")
        let menu = NSMenu()
        menu.addItem(withTitle: "Open videos folder", action: #selector(openVideos), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Wallpaper", action: #selector(quit), keyEquivalent: "").target = self
        item.menu = menu
        statusItem = item
    }

    private func buildWindows() {
        windows.forEach { $0.tearDown() }
        windows = NSScreen.screens.compactMap { screen in
            guard let url = videoURL(for: screen) else { return nil }
            NSLog("Wallpaper: %@ (%@) -> %@", screen.localizedName, pixelSize(of: screen), url.lastPathComponent)
            let window = WallpaperWindow(screen: screen, video: url)
            window.orderFront(nil)
            return window
        }
        updatePlayback()
    }

    @objc private func screensChanged() {
        // Wait for the screen arrangement to settle before rebuilding.
        NSObject.cancelPreviousPerformRequests(withTarget: self, selector: #selector(rebuild), object: nil)
        perform(#selector(rebuild), with: nil, afterDelay: 1.0)
    }

    @objc private func rebuild() { buildWindows() }

    /// Play only where the wallpaper can actually be seen.
    @objc private func updatePlayback() {
        let hiddenEverywhere = screensAsleep || screensaverOn || locked
        for window in windows {
            if !hiddenEverywhere && window.occlusionState.contains(.visible) {
                window.play()
            } else {
                window.pause()
            }
        }
    }

    @objc private func openVideos() {
        NSWorkspace.shared.open(videosFolder)
    }

    @objc private func quit() {
        windows.forEach { $0.tearDown() }
        NSApp.terminate(nil)
    }
}

@main
enum Main {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
    }
}
