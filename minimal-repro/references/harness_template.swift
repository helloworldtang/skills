// 最小复现装置模板（macOS/AppKit 案例：窗口结构 + 拆窗时序 + 确认音）
// 用法: swiftc -O -o harness main.swift && ./harness [enter|click]
// 改造指南: 按目标应用抄窗口结构(styleMask/level/canBecomeKey/child window),
// 驱动保留 sendEvent 骨架, 日志点埋在你怀疑的时序节点上。
import AppKit

final class OverlayPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

final class ToolbarPanel: NSPanel {
    override var canBecomeKey: Bool { false }
}

final class HoverButton: NSButton {
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for area in trackingAreas { removeTrackingArea(area) }
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self, userInfo: nil))
    }
    override func mouseEntered(with event: NSEvent) { layer?.backgroundColor = NSColor(white: 0.35, alpha: 1).cgColor }
    override func mouseExited(with event: NSEvent) { layer?.backgroundColor = .clear }
}

final class OverlayView: NSView {
    var delegateFinish: (() -> Void)?
    private var isFinishing = false
    private(set) var toolbar: ToolbarPanel?
    private(set) var button: HoverButton?

    override var acceptsFirstResponder: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.withAlphaComponent(0.3).setFill()
        bounds.fill()
    }

    func showToolbar() {
        let tb = ToolbarPanel(
            contentRect: NSRect(x: 0, y: 0, width: 200, height: 40),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false)
        tb.level = .popUpMenu
        tb.backgroundColor = NSColor(white: 0.2, alpha: 1)
        tb.hasShadow = true
        tb.isReleasedWhenClosed = false

        let btn = HoverButton(title: "✓", target: nil, action: nil)
        btn.isBordered = false
        btn.bezelStyle = .inline
        btn.wantsLayer = true
        btn.layer?.cornerRadius = 6
        btn.frame = NSRect(x: 10, y: 5, width: 30, height: 30)
        btn.target = self
        btn.action = #selector(confirmClicked)
        tb.contentView?.addSubview(btn)
        tb.setFrameOrigin(NSPoint(x: 300, y: 300))
        if let overlay = window {
            overlay.addChildWindow(tb, ordered: .above)
        }
        toolbar = tb
        button = btn
    }

    @objc private func confirmClicked() { confirm() }

    func confirm() {
        log("POP")
        NSSound(named: "Pop")?.play()
        finish()
    }

    private func finish() {
        guard !isFinishing else { return }
        isFinishing = true
        let tb = toolbar
        toolbar = nil
        log("finish-sync")
        DispatchQueue.main.async(execute: { [weak self] in
            log("teardown-begin")
            if let overlay = self?.window, let tb {
                overlay.removeChildWindow(tb)
                tb.close()
                log("toolbar-closed")
            }
            self?.delegateFinish?()
        })
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 36 {
            confirm()
            return
        }
        super.keyDown(with: event)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

var overlayWindow: NSPanel?

func log(_ s: String) {
    print(String(format: "%.3f %@", CACurrentMediaTime(), s))
    fflush(stdout)
}

func after(_ delay: Double, _ block: @escaping () -> Void) {
    DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: block)
}

func buildOverlay() -> OverlayView {
    let screen = NSScreen.main!.frame
    let panel = OverlayPanel(
        contentRect: screen,
        styleMask: [.borderless, .nonactivatingPanel],
        backing: .buffered, defer: false)
    panel.level = .popUpMenu
    panel.backgroundColor = .clear
    panel.isOpaque = false
    panel.hasShadow = false
    panel.ignoresMouseEvents = false
    panel.hidesOnDeactivate = false
    panel.isReleasedWhenClosed = false
    panel.becomesKeyOnlyIfNeeded = false

    let view = OverlayView(frame: NSRect(origin: .zero, size: screen.size))
    view.delegateFinish = {
        log("closeOverlay-begin")
        overlayWindow?.contentView = nil
        overlayWindow?.orderOut(nil)
        overlayWindow?.close()
        overlayWindow = nil
        log("closeOverlay-done")
    }
    panel.contentView = view
    panel.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
    overlayWindow = panel
    return view
}

let mode = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "enter"

after(1.0) {
    let view = buildOverlay()
    log("overlay-up")
    view.showToolbar()
    log("toolbar-up")

    after(1.0) {
        if mode == "enter" {
            let kd = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [],
                                      timestamp: CACurrentMediaTime(), windowNumber: overlayWindow!.windowNumber,
                                      context: nil, characters: "\r", charactersIgnoringModifiers: "\r",
                                      isARepeat: false, keyCode: 36)!
            log("send-keyDown")
            app.sendEvent(kd)
            log("keyDown-returned")
            after(0.08) {
                let ku = NSEvent.keyEvent(with: .keyUp, location: .zero, modifierFlags: [],
                                          timestamp: CACurrentMediaTime(), windowNumber: 0,
                                          context: nil, characters: "\r", charactersIgnoringModifiers: "\r",
                                          isARepeat: false, keyCode: 36)!
                log("send-keyUp")
                app.sendEvent(ku)
                log("keyUp-returned")
                after(1.5) {
                    log("quit")
                    app.terminate(nil)
                }
            }
        } else {
            guard let tb = view.toolbar, let btn = view.button else { app.terminate(nil); return }
            let btnInWin = btn.convert(btn.bounds, to: nil)
            let center = CGPoint(x: btnInWin.midX, y: btnInWin.midY)
            let down = NSEvent.mouseEvent(with: .leftMouseDown, location: center, modifierFlags: [],
                                          timestamp: CACurrentMediaTime(), windowNumber: tb.windowNumber,
                                          context: nil, eventNumber: 1, clickCount: 1, pressure: 1)!
            log("send-mouseDown")
            app.sendEvent(down)
            log("mouseDown-returned")
            after(0.06) {
                let up = NSEvent.mouseEvent(with: .leftMouseUp, location: center, modifierFlags: [],
                                            timestamp: CACurrentMediaTime(), windowNumber: tb.windowNumber,
                                            context: nil, eventNumber: 2, clickCount: 1, pressure: 0)!
                log("send-mouseUp")
                app.sendEvent(up)
                log("mouseUp-returned")
                after(0.15) {
                    let mv = NSEvent.mouseEvent(with: .mouseMoved, location: NSPoint(x: center.x, y: center.y + 50),
                                                modifierFlags: [], timestamp: CACurrentMediaTime(),
                                                windowNumber: 0, context: nil, eventNumber: 3, clickCount: 0, pressure: 0)!
                    log("send-mouseMoved")
                    app.sendEvent(mv)
                    log("mouseMoved-returned")
                    after(1.5) {
                        log("quit")
                        app.terminate(nil)
                    }
                }
            }
        }
    }
}

app.run()
