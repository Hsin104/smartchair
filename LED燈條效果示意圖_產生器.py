# 產生「LED 燈條效果示意圖」HTML（再用 Edge headless 轉 PNG）
# 用法：python LED燈條效果示意圖_產生器.py 輸出.html   → 印出畫布高度
# 轉圖：msedge --headless=new --force-device-scale-factor=2.5 --window-size=1200,<高度> --screenshot=out.png file:///.../輸出.html
import colorsys, sys

N = 35                      # 每條燈珠數
W = 1200                    # 畫布寬（窄一點，放進報告縮放後字比較大）
FONT = "'Times New Roman','DFKai-SB','標楷體',serif"   # 英數用 Times New Roman，中文用標楷體
OFF = (0x2e, 0x32, 0x39)


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in rgb)


def sit_color(t):
    # 綠 → 黃 → 紅（以人眼看到的色相呈現；韌體為 r+g=255 漸變）
    r, g, b = colorsys.hsv_to_rgb((1 - t) * 120 / 360, 0.9, 1.0)
    return (r * 255, g * 255, b * 255)


def led_pos(i):
    return 2 * (1 - abs(2 * i / (N - 1) - 1)) - 1   # 兩端 -1（扶手後端）、中段 +1（扶手前端）


def pct_of(side, tl, tf, i):
    # 與韌體 ledUpdate() 相同：s = ±左傾 + 前傾 × 位置，亮度 = 50% ± 30%
    s = max(-1, min(1, side * tl + tf * led_pos(i)))
    return 50 + s * 30


def shade(base, pct):
    k = pct / 80
    return hexc(tuple(o + (v - o) * k for v, o in zip(base, OFF)))


def pct_color(p):
    return "#ffffff" if p >= 75 else ("#b9c0c9" if p >= 45 else "#6c7480")


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


def strip_dots(pts, colors, pcts, r=4.6):
    out = []
    for (x, y), c, p in zip(pts, colors, pcts):
        op = 0.15 + (p - 20) / 60 * 0.75
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r*2.3:.1f}" fill="{c}" opacity="{op:.2f}" filter="url(#glow)"/>')
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{c}"/>')
    return "".join(out)


CARD_W, CARD_H = 236, 300


def mini_chair(ox, oy, sc, title, tl, tf, base, sub):
    """俯視圖：上 = 前方、下 = 椅背，左右與使用者相同（從椅背後上方看）"""
    w, h = CARD_W, CARD_H
    g = [f'<g transform="translate({ox},{oy}) scale({sc})">',
         f'<rect x="0" y="0" width="{w}" height="{h}" rx="14" fill="#1f2329"/>']
    ax = {"L": (34, 66), "R": (170, 202)}
    ay0, ay1 = 70, 232
    seat = (78, 80, 158, 222)
    g.append(f'<text x="{w/2}" y="38" text-anchor="middle" fill="#9aa1ab" font-size="14">▲ 前方</text>')
    g.append(f'<rect x="{seat[0]}" y="{seat[1]}" width="{seat[2]-seat[0]}" height="{seat[3]-seat[1]}" rx="10" fill="#3b4048" stroke="#555c66"/>')
    g.append(f'<rect x="82" y="234" width="72" height="24" rx="7" fill="#4a5059" stroke="#5d646e"/>')
    g.append(f'<text x="{w/2}" y="251" text-anchor="middle" fill="#d0d4da" font-size="14">椅背</text>')
    for x0, x1 in ax.values():
        g.append(f'<rect x="{x0}" y="{ay0}" width="{x1-x0}" height="{ay1-ay0}" rx="8" fill="#4a5059" stroke="#5d646e"/>')
    # 重心點
    mx, my = (seat[0] + seat[2]) / 2, (seat[1] + seat[3]) / 2
    cx, cy = mx - tl * 26, my - tf * 34
    g.append(f'<circle cx="{mx}" cy="{my}" r="16" fill="none" stroke="#6fcf73" stroke-dasharray="4 3" opacity=".7"/>')
    if tl or tf:
        g.append(f'<line x1="{mx}" y1="{my}" x2="{cx:.1f}" y2="{cy:.1f}" stroke="#ff7a6b" stroke-width="2" marker-end="url(#arrow)"/>')
    g.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6.5" fill="#ff5a4a" stroke="white" stroke-width="1.5"/>')
    pad = 9
    for side, key, x_out, x_in in ((1, "L", ax["L"][0] - pad, ax["L"][1] + pad),
                                   (-1, "R", ax["R"][1] + pad, ax["R"][0] - pad)):
        pts = u_path(x_out, x_in, ay1 - 2, ay0 - pad, N)
        pcts = [pct_of(side, tl, tf, i) for i in range(N)]
        g.append(strip_dots(pts, [shade(base, p) for p in pcts], pcts))
        front, back = pcts[N // 2], pcts[0]
        axc = (ax[key][0] + ax[key][1]) / 2
        g.append(f'<text x="{axc}" y="{ay0-pad-12}" text-anchor="middle" fill="{pct_color(front)}" font-size="15" font-weight="700">前{front:.0f}%</text>')
        g.append(f'<text x="{axc}" y="{ay1+26}" text-anchor="middle" fill="{pct_color(back)}" font-size="15" font-weight="700">後{back:.0f}%</text>')
    g.append(f'<text x="50" y="{h-12}" text-anchor="middle" fill="#9aa1ab" font-size="14">左扶手</text>')
    g.append(f'<text x="186" y="{h-12}" text-anchor="middle" fill="#9aa1ab" font-size="14">右扶手</text>')
    g.append('</g>')
    cw, ch = w * sc, h * sc
    g.append(f'<text x="{ox + cw/2}" y="{oy + ch + 40}" text-anchor="middle" fill="#141a24" font-size="30" font-weight="700">{title}</text>')
    g.append(f'<text x="{ox + cw/2}" y="{oy + ch + 74}" text-anchor="middle" fill="#4d5665" font-size="22">{sub}</text>')
    return "".join(g)


def section_head(y, num, title, sub, sub_y=None):
    s = [f'<circle cx="82" cy="{y}" r="21" fill="#141a24"/>',
         f'<text x="82" y="{y+9}" text-anchor="middle" fill="white" font-size="26" font-weight="700">{num}</text>',
         f'<text x="116" y="{y+12}" font-size="34" font-weight="700" fill="#141a24">{title}</text>']
    if sub:
        if sub_y is None:
            s.append(f'<text x="380" y="{y+10}" font-size="22" fill="#4d5665">{sub}</text>')
        else:
            s.append(f'<text x="116" y="{sub_y}" font-size="22" fill="#4d5665">{sub}</text>')
    return "".join(s)


def build():
    s = []
    # ── 版面 ──
    y0 = 190                    # ① 卡片頂
    c1h = 575
    y1 = y0 + c1h + 30          # ② 卡片頂
    sc = 1.35
    cw, ch = CARD_W * sc, CARD_H * sc
    row_h = ch + 105
    rows_top = y1 + 140
    legend_y = rows_top + 2 * row_h + 30
    c2h = legend_y + 125 - y1
    H = int(y1 + c2h + 30)

    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">')
    s.append('''<defs>
      <filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="4"/></filter>
      <marker id="arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#ff7a6b"/></marker>
      <linearGradient id="sitgrad" x1="0" x2="1">''')
    for k in range(11):
        s.append(f'<stop offset="{k/10}" stop-color="{hexc(sit_color(k/10))}"/>')
    s.append('</linearGradient></defs>')
    s.append(f'<rect width="{W}" height="{H}" fill="#f6f7f9"/>')

    # 標題
    s.append('<text x="50" y="78" font-size="50" font-weight="700" fill="#141a24">智慧座椅 LED 燈條效果示意</text>')
    s.append('<text x="52" y="126" font-size="24" fill="#3d4450">左右扶手各一條燈條（各 35 顆），沿扶手外側 → 前端 → 內側包覆。</text>')
    s.append('<text x="52" y="162" font-size="24" fill="#141a24" font-weight="700">顏色表示久坐時間，亮度表示坐姿重心。</text>')

    # ── ① 顏色 ──
    s.append(f'<rect x="30" y="{y0}" width="{W-60}" height="{c1h}" rx="20" fill="white" stroke="#e1e4ea"/>')
    s.append(section_head(y0 + 52, 1, "顏色：久坐時間", "依醫療建議，連續坐 30 分鐘應起身活動"))

    bx0, bx1, by = 110, 1090, y0 + 175
    for t in (0, 0.25, 0.5, 0.75, 1.0):        # 燈條色票
        x = bx0 + (bx1 - bx0) * t
        c = hexc(sit_color(t))
        n, sp = 8, 12.5
        pts = [(x - (n - 1) * sp / 2 + k * sp, by - 48) for k in range(n)]
        s.append(f'<rect x="{x - n*sp/2 - 8}" y="{by-65}" width="{n*sp+16}" height="34" rx="17" fill="#1f2329"/>')
        s.append(strip_dots(pts, [c] * n, [60] * n, r=4.3))
    s.append(f'<rect x="{bx0}" y="{by}" width="{bx1-bx0}" height="30" rx="15" fill="url(#sitgrad)"/>')
    for t, lab, desc in ((0, "0 分", "剛坐下・綠色"), (0.5, "15 分", "黃色（平滑漸變）"), (1, "30 分", "紅色")):
        x = bx0 + (bx1 - bx0) * t
        s.append(f'<line x1="{x}" y1="{by-8}" x2="{x}" y2="{by+38}" stroke="#141a24" stroke-width="2.5"/>')
        anchor = "start" if t == 0 else ("end" if t == 1 else "middle")
        xx = x - 12 if t == 0 else (x + 12 if t == 1 else x)
        s.append(f'<text x="{xx}" y="{by+72}" text-anchor="{anchor}" font-size="28" font-weight="700" fill="#141a24">{lab}</text>')
        s.append(f'<text x="{xx}" y="{by+104}" text-anchor="{anchor}" font-size="22" fill="#4d5665">{desc}</text>')

    # 30 分鐘之後
    ty = y0 + 325
    s.append(f'<text x="76" y="{ty}" font-size="26" font-weight="700" fill="#a12a1d">滿 30 分鐘之後：</text>')
    steps = [("① 剛滿 30 分鐘", "4 顆馬達震動＋閃爍 10 秒", True),
             ("② 接著", "保持紅色常亮", False),
             ("③ 每再過 5 分鐘", "再震動一次＋閃爍 10 秒", True)]
    bw, gap = 340, 18
    bx = (W - (3 * bw + 2 * gap)) / 2
    for k, (a, b, blink) in enumerate(steps):
        x = bx + k * (bw + gap)
        yy = ty + 20
        s.append(f'<rect x="{x}" y="{yy}" width="{bw}" height="120" rx="14" fill="#fff4f2" stroke="#f3c4bd"/>')
        for j in range(8):
            on = (j % 2 == 0) if blink else True
            s.append(f'<circle cx="{x+30+j*20}" cy="{yy+30}" r="6.5" fill="{"#ff2d1a" if on else "#5a2a26"}"/>')
        s.append(f'<text x="{x+22}" y="{yy+74}" font-size="26" font-weight="700" fill="#a12a1d">{a}</text>')
        s.append(f'<text x="{x+22}" y="{yy+106}" font-size="22" fill="#2b3340">{b}</text>')

    ry = y0 + 480
    s.append(f'<rect x="60" y="{ry}" width="{W-120}" height="80" rx="12" fill="#f1f4f8"/>')
    s.append(f'<text x="84" y="{ry+33}" font-size="22" fill="#2b3340">'
             f'<tspan font-weight="700">計時規則：</tspan>換姿勢、短暫起身（30 秒內）<tspan font-weight="700">不會中斷計時</tspan>；</text>')
    s.append(f'<text x="84" y="{ry+65}" font-size="22" fill="#2b3340">'
             f'離座滿 30 秒（例如去洗手間）才算起身活動，計時歸零、燈條回到綠色。</text>')

    # ── ② 亮度 ──
    s.append(f'<rect x="30" y="{y1}" width="{W-60}" height="{c2h}" rx="20" fill="white" stroke="#e1e4ea"/>')
    s.append(section_head(y1 + 52, 2, "亮度：坐姿重心", "重心偏向哪邊，那邊的燈就越亮；基準 50%，最低 20%、最高 80%（省電並保護元件）", sub_y=y1 + 102))

    green = sit_color(0)
    cases = [("正常坐姿", 0, 0, "全部 50%"),
             ("左傾", 1, 0, "左條亮、右條暗"),
             ("右傾", -1, 0, "右條亮、左條暗"),
             ("前傾", 0, 1, "中段（扶手前端）亮"),
             ("後仰", 0, -1, "兩端（扶手後端）亮"),
             ("左傾＋前傾", 1, 1, "可疊加：左前最亮、右後最暗")]
    gap = 34
    x_start = (W - (3 * cw + 2 * gap)) / 2
    for k, (title, tl, tf, sub) in enumerate(cases):
        r, c = divmod(k, 3)
        s.append(mini_chair(x_start + c * (cw + gap), rows_top + r * row_h, sc, title, tl, tf, green, sub))

    # 圖例
    ly = legend_y
    s.append(f'<text x="70" y="{ly+8}" font-size="22" fill="#2b3340" font-weight="700">圖例</text>')
    lx = 136
    for p, lab in ((20, "20% 最暗"), (50, "50% 基準"), (80, "80% 最亮")):
        s.append(f'<rect x="{lx}" y="{ly-15}" width="40" height="32" rx="16" fill="#1f2329"/>')
        s.append(strip_dots([(lx + 20, ly + 1)], [shade(green, p)], [p], r=6.5))
        s.append(f'<text x="{lx+50}" y="{ly+8}" font-size="22" fill="#2b3340">{lab}</text>')
        lx += 175
    s.append(f'<circle cx="{lx+16}" cy="{ly+1}" r="8" fill="#ff5a4a" stroke="white" stroke-width="1.5"/>')
    s.append(f'<text x="{lx+32}" y="{ly+8}" font-size="22" fill="#2b3340">重心位置（虛線圈＝中立範圍）</text>')
    s.append(f'<text x="70" y="{ly+50}" font-size="20" fill="#5b6472">註：俯視圖為從椅背後上方往前看（上＝前方），左右與使用者相同。</text>')
    s.append(f'<text x="70" y="{ly+80}" font-size="20" fill="#5b6472">　　圖中為傾斜到最大時的亮度，實際亮度會依重心偏移程度連續變化。</text>')
    s.append('</svg>')
    return "\n".join(s), H


svg, H = build()
html = f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:#f6f7f9}}</style></head><body>{svg}</body></html>'
open(sys.argv[1], "w", encoding="utf-8").write(html)
print(H)
