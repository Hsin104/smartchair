# 產生「LED 燈條效果示意圖（橫版，給簡報用）」HTML，再用 Edge headless 轉 PNG
# 用法：python LED燈條效果示意圖_橫版_產生器.py 輸出.html  → 印出 寬 高
# 簡報上能用的空間小，所以只留重點、字放大（最小 20px，畫布 1200 寬約等於投影片寬）
import colorsys, sys

N = 35
W, H = 1200, 645
FONT = "'Times New Roman','DFKai-SB','標楷體',serif"
OFF = (0x2e, 0x32, 0x39)


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in rgb)


def sit_color(t):
    r, g, b = colorsys.hsv_to_rgb((1 - t) * 120 / 360, 0.9, 1.0)
    return (r * 255, g * 255, b * 255)


def led_pos(i):
    return 2 * (1 - abs(2 * i / (N - 1) - 1)) - 1


def pct_of(side, tl, tf, i):
    s = max(-1, min(1, side * tl + tf * led_pos(i)))
    return 50 + s * 30


def shade(base, pct):
    k = pct / 80
    return hexc(tuple(o + (v - o) * k for v, o in zip(base, OFF)))


def u_path(x_out, x_in, y_back, y_front, n):
    segs = [((x_out, y_back), (x_out, y_front)), ((x_out, y_front), (x_in, y_front)), ((x_in, y_front), (x_in, y_back))]
    lens = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in segs]
    tot = sum(lens)
    pts = []
    for i in range(n):
        d = tot * i / (n - 1)
        for (a, b), L in zip(segs, lens):
            if d <= L + 1e-9 or (a, b) == segs[-1]:
                t = d / L if L else 0
                pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                break
            d -= L
    return pts


def dots(pts, colors, pcts, r):
    out = []
    for (x, y), c, p in zip(pts, colors, pcts):
        op = 0.15 + (p - 20) / 60 * 0.75
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r*2.3:.1f}" fill="{c}" opacity="{op:.2f}" filter="url(#glow)"/>')
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{c}"/>')
    return "".join(out)


def mini(ox, oy, title, sub, tl, tf, base):
    w, h = 180, 222
    g = [f'<g transform="translate({ox},{oy})">', f'<rect width="{w}" height="{h}" rx="14" fill="#1f2329"/>']
    al, ar = (26, 50), (130, 154)
    ay0, ay1 = 36, 184
    seat = (64, 44, 116, 178)
    g.append(f'<rect x="{seat[0]}" y="{seat[1]}" width="{seat[2]-seat[0]}" height="{seat[3]-seat[1]}" rx="8" fill="#3b4048" stroke="#555c66"/>')
    g.append(f'<rect x="60" y="192" width="60" height="18" rx="6" fill="#4a5059" stroke="#5d646e"/>')
    for x0, x1 in (al, ar):
        g.append(f'<rect x="{x0}" y="{ay0}" width="{x1-x0}" height="{ay1-ay0}" rx="7" fill="#4a5059" stroke="#5d646e"/>')
    mx, my = (seat[0] + seat[2]) / 2, (seat[1] + seat[3]) / 2
    cx, cy = mx - tl * 17, my - tf * 30
    g.append(f'<circle cx="{mx}" cy="{my}" r="12" fill="none" stroke="#6fcf73" stroke-dasharray="3 3" opacity=".7"/>')
    if tl or tf:
        g.append(f'<line x1="{mx}" y1="{my}" x2="{cx:.1f}" y2="{cy:.1f}" stroke="#ff7a6b" stroke-width="2"/>')
    g.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="#ff5a4a" stroke="white" stroke-width="1.5"/>')
    pad = 8
    for side, (x0, x1), x_out, x_in in ((1, al, al[0] - pad, al[1] + pad), (-1, ar, ar[1] + pad, ar[0] - pad)):
        pts = u_path(x_out, x_in, ay1 - 2, ay0 - pad, N)
        pcts = [pct_of(side, tl, tf, i) for i in range(N)]
        g.append(dots(pts, [shade(base, p) for p in pcts], pcts, 3.6))
    g.append('</g>')
    g.append(f'<text x="{ox + w/2}" y="{oy + h + 36}" text-anchor="middle" font-size="28" font-weight="700" fill="#141a24">{title}</text>')
    g.append(f'<text x="{ox + w/2}" y="{oy + h + 68}" text-anchor="middle" font-size="23" fill="#3d4450">{sub}</text>')
    return "".join(g)


def badge(x, y, num):
    return (f'<circle cx="{x}" cy="{y}" r="19" fill="#141a24"/>'
            f'<text x="{x}" y="{y+8}" text-anchor="middle" fill="white" font-size="24" font-weight="700">{num}</text>')


def build():
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">',
         '<defs><filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="3.5"/></filter>'
         '<marker id="arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#c0392b"/></marker>'
         '<linearGradient id="sg" x1="0" x2="1">']
    for k in range(11):
        s.append(f'<stop offset="{k/10}" stop-color="{hexc(sit_color(k/10))}"/>')
    s.append('</linearGradient></defs>')
    s.append(f'<rect width="{W}" height="{H}" fill="white"/>')

    # ── ① 顏色 ──
    s.append(badge(34, 34, 1))
    s.append('<text x="64" y="45" font-size="32" font-weight="700" fill="#141a24">顏色＝久坐時間</text>')
    s.append('<text x="300" y="44" font-size="23" fill="#3d4450">（連續坐 30 分鐘應起身活動）</text>')
    bx0, bx1, by = 40, 715, 128
    for t in (0, 0.5, 1.0):
        x = bx0 + (bx1 - bx0) * t
        x = min(max(x, bx0 + 62), bx1 - 62)
        n, sp = 9, 12
        pts = [(x - (n - 1) * sp / 2 + k * sp, by - 34) for k in range(n)]
        s.append(f'<rect x="{x - n*sp/2 - 8}" y="{by-50}" width="{n*sp+16}" height="32" rx="16" fill="#1f2329"/>')
        s.append(dots(pts, [hexc(sit_color(t))] * n, [60] * n, 4.2))
    s.append(f'<rect x="{bx0}" y="{by}" width="{bx1-bx0}" height="28" rx="14" fill="url(#sg)"/>')
    for t, lab in ((0, "0 分・綠"), (0.5, "15 分・黃"), (1, "30 分・紅")):
        x = bx0 + (bx1 - bx0) * t
        anchor = "start" if t == 0 else ("end" if t == 1 else "middle")
        s.append(f'<text x="{x}" y="{by+62}" text-anchor="{anchor}" font-size="27" font-weight="700" fill="#141a24">{lab}</text>')
    s.append(f'<text x="{bx0}" y="{by+100}" font-size="23" fill="#3d4450">換姿勢、短暫起身（30 秒內）<tspan font-weight="700" fill="#141a24">不中斷計時</tspan>；離座滿 30 秒才歸零</text>')

    # 30 分鐘之後
    px, pw = 775, 395
    s.append(f'<path d="M{bx1+8},{by+14} L{px-8},{by+14}" stroke="#c0392b" stroke-width="3" marker-end="url(#arrow)"/>')
    steps = [("滿 30 分", "全部震動＋閃 10 秒", True), ("之後", "紅色常亮", False), ("每 5 分", "再震動＋閃 10 秒", True)]
    for k, (a, b, blink) in enumerate(steps):
        yy = 66 + k * 56
        s.append(f'<rect x="{px}" y="{yy}" width="{pw}" height="48" rx="10" fill="#fff4f2" stroke="#f3c4bd"/>')
        for j in range(3):
            on = (j % 2 == 0) if blink else True
            s.append(f'<circle cx="{px+20+j*15}" cy="{yy+24}" r="5.5" fill="{"#ff2d1a" if on else "#5a2a26"}"/>')
        s.append(f'<text x="{px+66}" y="{yy+33}" font-size="24" fill="#2b3340"><tspan font-weight="700" fill="#a12a1d">{a}：</tspan>{b}</text>')

    s.append('<line x1="30" y1="252" x2="1170" y2="252" stroke="#e1e4ea" stroke-width="2"/>')

    # ── ② 亮度 ──
    s.append(badge(34, 296, 2))
    s.append('<text x="64" y="307" font-size="32" font-weight="700" fill="#141a24">亮度＝重心偏向</text>')
    s.append('<text x="300" y="306" font-size="23" fill="#3d4450">（基準 50%，最暗 20%、最亮 80%）</text>')
    green = sit_color(0)
    lx = 712
    for p, lab in ((20, "20%"), (50, "50%"), (80, "80%")):
        s.append(dots([(lx, 298)], [shade(green, p)], [p], 7))
        s.append(f'<text x="{lx+20}" y="306" font-size="23" fill="#3d4450">{lab}</text>')
        lx += 92
    s.append(f'<text x="{W-30}" y="306" text-anchor="end" font-size="20" fill="#5b6472">俯視・上＝前方</text>')

    cases = [("正常", "全部 50%", 0, 0), ("左傾", "左亮右暗", 1, 0), ("右傾", "右亮左暗", -1, 0),
             ("前傾", "前端亮", 0, 1), ("後仰", "後端亮", 0, -1), ("左傾＋前傾", "左前最亮", 1, 1)]
    cw, gap = 180, 16
    x0 = (W - (6 * cw + 5 * gap)) / 2
    for k, (t, sub, tl, tf) in enumerate(cases):
        s.append(mini(x0 + k * (cw + gap), 326, t, sub, tl, tf, green))
    s.append('</svg>')
    return "\n".join(s)


html = f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:white}}</style></head><body>{build()}</body></html>'
open(sys.argv[1], "w", encoding="utf-8").write(html)
print(W, H)
