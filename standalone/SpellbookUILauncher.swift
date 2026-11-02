import Cocoa
import WebKit
import Darwin

final class SpellbookLauncher: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    private var port = 7872
    private var backend: Process?
    private var window: NSWindow?
    private var webView: WKWebView?
    private var attempts = 0
    private var checkingBackend = false
    private var shuttingDown = false

    private var baseURL: URL { URL(string: "http://127.0.0.1:\(port)")! }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installEditMenu()
        startBackend()
        showLoadingWindow()
        checkBackend()
    }

    private func installEditMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(NSMenuItem(title: "Quit Spellbook UI", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(NSMenuItem(title: "Undo", action: Selector(("undo:")), keyEquivalent: "z"))
        let redo = NSMenuItem(title: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(redo)
        editMenu.addItem(.separator())
        editMenu.addItem(NSMenuItem(title: "Cut", action: Selector(("cut:")), keyEquivalent: "x"))
        editMenu.addItem(NSMenuItem(title: "Copy", action: Selector(("copy:")), keyEquivalent: "c"))
        editMenu.addItem(NSMenuItem(title: "Paste", action: Selector(("paste:")), keyEquivalent: "v"))
        editMenu.addItem(NSMenuItem(title: "Select All", action: Selector(("selectAll:")), keyEquivalent: "a"))
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)
        NSApp.mainMenu = mainMenu
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if shuttingDown { return .terminateNow }
        shuttingDown = true
        guard let backend else { return .terminateNow }
        var request = URLRequest(url: baseURL.appendingPathComponent("api/window/quit"))
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        URLSession.shared.dataTask(with: request) { [weak self] _, _, _ in
            backend.terminate()
            DispatchQueue.main.async { sender.reply(toApplicationShouldTerminate: true) }
            self?.backend = nil
        }.resume()
        return .terminateLater
    }

    private func availablePort() -> Int? {
        for candidate in 7872...7887 {
            let fd = socket(AF_INET, SOCK_STREAM, 0)
            guard fd >= 0 else { continue }
            var address = sockaddr_in()
            address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            address.sin_family = sa_family_t(AF_INET)
            address.sin_port = in_port_t(candidate).bigEndian
            address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
            let result = withUnsafePointer(to: &address) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
            close(fd)
            if result == 0 { return candidate }
        }
        return nil
    }

    private func startBackend() {
        guard let selectedPort = availablePort() else {
            showError("No free local port is available for Spellbook UI. Close another Spellbook window and try again.")
            return
        }
        port = selectedPort
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        // appRoot resolution — three sources, first one wins:
        //   1. SPELLBOOK_ROOT env var (set by the user or a wrapper script)
        //   2. Contents/Resources/spellbook-root.txt inside the .app bundle
        //   3. Two levels up from this executable (works when run as `swift SpellbookUILauncher.swift`)
        let appRoot: String = {
            if let envRoot = ProcessInfo.processInfo.environment["SPELLBOOK_ROOT"] {
                return envRoot
            }
            // Bundle path: executable is at Contents/MacOS/SpellbookUI,
            // so Contents/Resources/ is two levels up + Resources/
            let execURL = URL(fileURLWithPath: CommandLine.arguments.first ?? "")
            let resourcesURL = execURL.deletingLastPathComponent()   // Contents/MacOS
                .deletingLastPathComponent()                          // Contents
                .appendingPathComponent("Resources")
            let rootFile = resourcesURL.appendingPathComponent("spellbook-root.txt")
            if let stored = try? String(contentsOf: rootFile, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
               !stored.isEmpty {
                return stored
            }
            // Fallback: script-relative (dev mode — `swift SpellbookUILauncher.swift`)
            return execURL.deletingLastPathComponent()   // standalone/
                .deletingLastPathComponent()             // Spellbook-UI/
                .path
        }()
        let folder = "\(appRoot)/standalone"
        let python = "\(folder)/.venv/bin/python"
        let server = "\(folder)/server.py"
        let process = Process()
        // Launch through /usr/bin/env so macOS resolves the venv interpreter consistently from the app bundle.
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [python, server, "--port", "\(port)", "--native-window"]
        process.currentDirectoryURL = URL(fileURLWithPath: folder)
        var env = ProcessInfo.processInfo.environment
        env.removeValue(forKey: "VIRTUAL_ENV")
        env.removeValue(forKey: "VIRTUAL_ENV_PROMPT")
        env.removeValue(forKey: "VIRTUAL_ENV_DISABLE_PROMPT")
        // SPELLBOOK_APP_DIR is intentionally not set here: paths.py resolves the correct
        // platform default (~/Library/Application Support/Spellbook on macOS) on its own.
        // Only set SPELLBOOK_POSE_KIT if not already in the environment.
        if env["SPELLBOOK_POSE_KIT"] == nil {
            env["SPELLBOOK_POSE_KIT"] = "\(appRoot)/.pose-kit"
        }
        env["PYTHONUNBUFFERED"] = "1"
        env.removeValue(forKey: "SSL_CERT_DIR")
        env["SSL_CERT_FILE"] = "\(folder)/.venv/lib/python3.11/site-packages/certifi/cacert.pem"
        process.environment = env
        let logURL = URL(fileURLWithPath: "/tmp/spellbook-launch.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let log = try? FileHandle(forWritingTo: logURL) {
            try? log.truncate(atOffset: 0)
            let marker = "Spellbook UI launch: port=\(port), executable=/usr/bin/env, python=\(python), server=\(server), SSL_CERT_FILE=\(env["SSL_CERT_FILE"] ?? "unset")\n"
            try? log.write(contentsOf: Data(marker.utf8))
            try? log.seekToEnd()
            process.standardOutput = log
            process.standardError = log
        }
        process.terminationHandler = { [weak self] child in
            let reason = child.terminationReason == .uncaughtSignal ? "signal" : "exit"
            self?.appendLaunchLog("Backend terminated: reason=\(reason), status=\(child.terminationStatus), pid=\(child.processIdentifier)")
            DispatchQueue.main.async {
                guard let self, !self.shuttingDown else { return }
                self.showError("Spellbook UI’s local server stopped unexpectedly (\(reason) \(child.terminationStatus)). See /tmp/spellbook-launch.log for details.")
            }
        }
        do {
            try process.run()
            backend = process
        } catch {
            let details = error as NSError
            showError("Could not start Spellbook’s local server (\(details.domain) \(details.code)): \(error.localizedDescription). See /tmp/spellbook-launch.log.")
        }
    }

    private func checkBackend() {
        guard !checkingBackend else { return }
        checkingBackend = true
        // Prefer the backend this launcher spawned, probed in order rather than as a race:
        // dev servers started by hand often occupy 7872, and attaching the window to one of
        // those makes the app die the moment that server does. While our own backend process
        // is alive, wait for ITS port only — scan other ports just as a fallback (e.g. the
        // server shifted ports after a startup race) and for the "attach to running instance"
        // case when no backend was spawned by us.
        let own = port
        let ownAlive = backend?.isRunning ?? false
        probe(port: own) { ownOK in
            DispatchQueue.main.async {
                if ownOK { self.finishCheck(foundPort: own); return }
                if ownAlive && self.attempts < 240 { self.backendCheckRetry(); return }
                self.probeFirst(in: 7872...7887) { found in
                    DispatchQueue.main.async {
                        if let found { self.finishCheck(foundPort: found); return }
                        self.backendCheckRetry()
                    }
                }
            }
        }
    }

    private func finishCheck(foundPort: Int) {
        port = foundPort
        checkingBackend = false
        showWindow()
    }

    private func backendCheckRetry() {
        checkingBackend = false
        attempts += 1
        if attempts == 30 { setLoadingStage("Still starting — first launch can take a while…") }
        // First launch imports several image-processing libraries. Allow up to five minutes
        // before treating slow initialization as a failure.
        if attempts < 600 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.checkBackend() }
        } else {
            appendLaunchLog("Health check timed out after 300 seconds; backendRunning=\(backend?.isRunning ?? false)")
            showError("Spellbook UI’s local server did not start on ports 7872–7887 after five minutes. See /tmp/spellbook-launch.log for details.")
        }
    }

    private func probe(port candidate: Int, result: @escaping (Bool) -> Void) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(candidate)/api/health")!)
        request.timeoutInterval = 0.7
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let ok: Bool = {
                guard let http = response as? HTTPURLResponse, http.statusCode == 200, let data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      json["app"] as? String == "spellbook" else { return false }
                return true
            }()
            result(ok)
        }.resume()
    }

    private func probeFirst(in range: ClosedRange<Int>, result: @escaping (Int?) -> Void) {
        let group = DispatchGroup()
        let lock = NSLock()
        var foundPort: Int?
        for candidate in range {
            group.enter()
            var request = URLRequest(url: URL(string: "http://127.0.0.1:\(candidate)/api/health")!)
            request.timeoutInterval = 0.7
            URLSession.shared.dataTask(with: request) { data, response, _ in
                defer { group.leave() }
                guard let http = response as? HTTPURLResponse, http.statusCode == 200, let data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      json["app"] as? String == "spellbook" else { return }
                lock.lock()
                if foundPort == nil { foundPort = candidate }
                lock.unlock()
            }.resume()
        }
        group.notify(queue: .main) { result(foundPort) }
    }

    // Webview watching: if a required page fails to load (backend went away mid-session),
    // re-check the backend and load the page again instead of leaving a dead screen.
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        recoverWebView(reason: "load failed: \(error.localizedDescription)")
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        recoverWebView(reason: "provisional load failed: \(error.localizedDescription)")
    }

    private var recovering = false
    private func recoverWebView(reason: String) {
        guard !shuttingDown, !recovering else { return }
        recovering = true
        appendLaunchLog("WebView \(reason); polling backend for recovery")
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            self?.recovering = false
            self?.attempts = 0
            self?.checkBackend()
        }
    }

    private func makeWindow() {        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        let view = WKWebView(frame: .zero, configuration: config)
        view.autoresizingMask = [.width, .height]
        view.navigationDelegate = self
        let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1500, height: 980),
                           styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                           backing: .buffered, defer: false)
        win.title = "Spellbook UI"
        win.titlebarAppearsTransparent = true
        win.titleVisibility = .hidden
        win.minSize = NSSize(width: 1080, height: 680)
        win.center()
        win.contentView = view
        win.delegate = self
        window = win
        webView = view
    }

    private func showLoadingWindow() {
        guard window == nil else { return }
        makeWindow()
        webView?.loadHTMLString(loadingHTML, baseURL: nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func showWindow() {
        if window == nil { makeWindow() }
        webView?.load(URLRequest(url: baseURL))
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func setLoadingStage(_ text: String) {
        let escaped = text.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
        webView?.evaluateJavaScript("var s=document.getElementById('stage');if(s){s.textContent='\(escaped)';}", completionHandler: nil)
    }

    private var loadingHTML: String {
        """
        <!doctype html><html><head><meta charset="utf-8"><style>
        body { margin: 0; height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px; background: #0d0e10; color: #e8e6e3; font-family: -apple-system, Helvetica, Arial, sans-serif; }
        h1 { font-size: 20px; font-weight: 600; margin: 0; letter-spacing: 0.2px; }
        .bar { width: 180px; height: 3px; border-radius: 2px; background: rgba(255,255,255,0.14); overflow: hidden; }
        .bar span { display: block; height: 100%; width: 40%; border-radius: 2px; background: #e8e6e3; animation: slide 1.2s ease-in-out infinite; }
        @keyframes slide { 0% { transform: translateX(-110%); } 100% { transform: translateX(450%); } }
        p { margin: 0; font-size: 13px; color: #9a978f; }
        </style></head><body><h1>Spellbook UI</h1><div class="bar"><span></span></div><p id="stage">Starting local server…</p></body></html>
        """
    }

    private func appendLaunchLog(_ message: String) {
        let url = URL(fileURLWithPath: "/tmp/spellbook-launch.log")
        guard let log = try? FileHandle(forWritingTo: url) else { return }
        defer { try? log.close() }
        try? log.seekToEnd()
        try? log.write(contentsOf: Data((message + "\n").utf8))
    }

    private func showError(_ message: String) {
        shuttingDown = true
        appendLaunchLog("Launcher error: \(message)")
        if let backend, backend.isRunning { backend.terminate() }
        backend = nil
        let alert = NSAlert()
        alert.messageText = "Spellbook UI couldn’t open"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.addButton(withTitle: "OK")
        alert.runModal()
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)

// Set the dock icon. Resolution order:
//   1. Contents/Resources/icon.png  (compiled .app bundle)
//   2. icon.png next to this script (dev mode: `swift SpellbookUILauncher.swift`)
// If neither exists the system falls back to its default.
let _execURL = URL(fileURLWithPath: CommandLine.arguments.first ?? "")
let _bundleIcon = _execURL
    .deletingLastPathComponent()   // Contents/MacOS
    .deletingLastPathComponent()   // Contents
    .appendingPathComponent("Resources/icon.png")
let _scriptIcon = _execURL.deletingLastPathComponent().appendingPathComponent("icon.png")
let _iconPath = [_bundleIcon, _scriptIcon].first { FileManager.default.fileExists(atPath: $0.path) }?.path ?? ""
if let _icon = NSImage(contentsOfFile: _iconPath) {
    app.applicationIconImage = _icon
}

let delegate = SpellbookLauncher()
app.delegate = delegate
app.run()
