// Gera o ícone do HollyAssinador (PNG 1024 + .iconset + .icns) desenhando em código.
//
// Uso (na pasta do projeto):  swift assets/make_icon.swift assets
// Saída: assets/icon_1024.png e assets/HollyAssinador.icns
import AppKit

func color(_ hex: UInt32, _ alpha: CGFloat = 1) -> NSColor {
    NSColor(
        srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
        green: CGFloat((hex >> 8) & 0xFF) / 255,
        blue: CGFloat(hex & 0xFF) / 255,
        alpha: alpha)
}

/// Polígono com cantos arredondados (um raio por vértice).
func roundedPolygon(_ pts: [NSPoint], radii: [CGFloat]) -> NSBezierPath {
    let path = NSBezierPath()
    let n = pts.count
    path.move(to: NSPoint(x: (pts[n - 1].x + pts[0].x) / 2, y: (pts[n - 1].y + pts[0].y) / 2))
    for i in 0..<n {
        path.appendArc(from: pts[i], to: pts[(i + 1) % n], radius: radii[i])
    }
    path.close()
    return path
}

/// Curva suave (Catmull-Rom) passando pelos pontos.
func smoothCurve(_ p: [NSPoint]) -> NSBezierPath {
    let path = NSBezierPath()
    path.move(to: p[0])
    for i in 0..<(p.count - 1) {
        let p0 = p[max(i - 1, 0)], p1 = p[i], p2 = p[i + 1], p3 = p[min(i + 2, p.count - 1)]
        let c1 = NSPoint(x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6)
        let c2 = NSPoint(x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6)
        path.curve(to: p2, controlPoint1: c1, controlPoint2: c2)
    }
    return path
}

func withShadow(_ blur: CGFloat, _ dy: CGFloat, _ c: NSColor, _ body: () -> Void) {
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowBlurRadius = blur
    shadow.shadowOffset = NSSize(width: 0, height: dy)
    shadow.shadowColor = c
    shadow.set()
    body()
    NSGraphicsContext.restoreGraphicsState()
}

func drawIcon(pixels: Int) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8,
        samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
        bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let scale = NSAffineTransform()
    scale.scale(by: CGFloat(pixels) / 1024)
    scale.concat()

    // --- corpo do ícone (grade do macOS: 824 pt dentro de 1024) ---
    let body = NSBezierPath(roundedRect: NSRect(x: 100, y: 100, width: 824, height: 824),
                            xRadius: 185, yRadius: 185)
    withShadow(24, -12, NSColor.black.withAlphaComponent(0.4)) {
        color(0x0A1633).setFill()
        body.fill()
    }
    NSGraphicsContext.saveGraphicsState()
    body.addClip()
    NSGradient(colors: [color(0x16306B), color(0x050B22)])!.draw(in: body.bounds, angle: -90)
    NSGradient(colors: [color(0x4A78E8, 0.50), color(0x4A78E8, 0)])!
        .draw(fromCenter: NSPoint(x: 330, y: 880), radius: 0,
              toCenter: NSPoint(x: 330, y: 880), radius: 560, options: [])

    // --- documento com a dobra no canto ---
    let doc = roundedPolygon(
        [NSPoint(x: 270, y: 225), NSPoint(x: 270, y: 805), NSPoint(x: 548, y: 805),
         NSPoint(x: 660, y: 693), NSPoint(x: 660, y: 225)],
        radii: [30, 30, 12, 12, 30])
    withShadow(36, -18, NSColor.black.withAlphaComponent(0.55)) {
        color(0xFFFFFF).setFill()
        doc.fill()
    }
    NSGraphicsContext.saveGraphicsState()
    doc.addClip()
    NSGradient(colors: [color(0xFFFFFF), color(0xDCE5F6)])!.draw(in: doc.bounds, angle: -90)
    NSGraphicsContext.restoreGraphicsState()

    let flap = roundedPolygon(
        [NSPoint(x: 548, y: 805), NSPoint(x: 660, y: 693), NSPoint(x: 548, y: 693)],
        radii: [8, 8, 8])
    withShadow(10, -4, NSColor.black.withAlphaComponent(0.25)) {
        color(0xBFCDEC).setFill()
        flap.fill()
    }

    // --- linhas de texto ---
    color(0xB1BEDA).setFill()
    for (y, w) in [(716.0, 196.0), (660.0, 290.0), (604.0, 236.0)] {
        NSBezierPath(roundedRect: NSRect(x: 322, y: y, width: w, height: 24),
                     xRadius: 12, yRadius: 12).fill()
    }

    // --- assinatura (traço verde-água luminoso) ---
    let signature = smoothCurve([
        NSPoint(x: 322, y: 396), NSPoint(x: 350, y: 518), NSPoint(x: 384, y: 400),
        NSPoint(x: 418, y: 474), NSPoint(x: 452, y: 388), NSPoint(x: 500, y: 366),
        NSPoint(x: 552, y: 418), NSPoint(x: 610, y: 456),
    ])
    signature.lineCapStyle = .round
    signature.lineJoinStyle = .round
    withShadow(26, 0, color(0x1FE0B0, 0.9)) {
        signature.lineWidth = 24
        color(0x18C99B).setStroke()
        signature.stroke()
    }
    signature.lineWidth = 24
    color(0x20D8A8).setStroke()
    signature.stroke()
    let underline = NSBezierPath()
    underline.move(to: NSPoint(x: 322, y: 304))
    underline.line(to: NSPoint(x: 606, y: 304))
    underline.lineWidth = 9
    underline.lineCapStyle = .round
    color(0xB1BEDA).setStroke()
    underline.stroke()

    // --- selo de verificação em dourado ---
    let center = NSPoint(x: 704, y: 272)
    let radius: CGFloat = 132
    let seal = NSBezierPath(ovalIn: NSRect(x: center.x - radius, y: center.y - radius,
                                           width: radius * 2, height: radius * 2))
    withShadow(30, -14, NSColor.black.withAlphaComponent(0.6)) {
        color(0x10265A).setFill()
        seal.fill()
    }
    NSGraphicsContext.saveGraphicsState()
    seal.addClip()
    NSGradient(colors: [color(0x23468F), color(0x0B1B45)])!.draw(in: seal.bounds, angle: -90)
    NSGraphicsContext.restoreGraphicsState()
    let ring = NSBezierPath(ovalIn: NSRect(x: center.x - radius + 8, y: center.y - radius + 8,
                                           width: (radius - 8) * 2, height: (radius - 8) * 2))
    ring.lineWidth = 12
    color(0xE9B949).setStroke()
    ring.stroke()
    let check = NSBezierPath()
    check.move(to: NSPoint(x: center.x - 58, y: center.y + 6))
    check.line(to: NSPoint(x: center.x - 16, y: center.y - 38))
    check.line(to: NSPoint(x: center.x + 62, y: center.y + 56))
    check.lineWidth = 34
    check.lineCapStyle = .round
    check.lineJoinStyle = .round
    withShadow(14, 0, color(0xF5CF6B, 0.7)) {
        color(0xF3C75A).setStroke()
        check.stroke()
    }

    NSGraphicsContext.restoreGraphicsState()  // clip do corpo
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

func write(_ rep: NSBitmapImageRep, to path: String) {
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
}

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "assets"
let iconset = "\(out)/HollyAssinador.iconset"
try? FileManager.default.removeItem(atPath: iconset)
try! FileManager.default.createDirectory(atPath: iconset, withIntermediateDirectories: true)

write(drawIcon(pixels: 1024), to: "\(out)/icon_1024.png")
for base in [16, 32, 128, 256, 512] {
    write(drawIcon(pixels: base), to: "\(iconset)/icon_\(base)x\(base).png")
    write(drawIcon(pixels: base * 2), to: "\(iconset)/icon_\(base)x\(base)@2x.png")
}

let task = Process()
task.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
task.arguments = ["-c", "icns", iconset, "-o", "\(out)/HollyAssinador.icns"]
try! task.run()
task.waitUntilExit()
try? FileManager.default.removeItem(atPath: iconset)
print(task.terminationStatus == 0 ? "ok: \(out)/HollyAssinador.icns" : "falha no iconutil")
