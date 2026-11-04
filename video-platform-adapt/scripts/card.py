#!/usr/bin/env python3
"""card.py — 生成开场卡（多画幅）。

开场卡的唯一目的是：让划到前 3 秒的人立刻知道"这是真机录屏，不是剪辑"。
所以文字必须满足：能一秒读完、字号在手机上不糊、层级只有三级。

用法:
    python3 scripts/card.py --ratio 3:4 -o card.png \
        --line "本机真机录屏 · 未剪辑 · 未加速" \
        --headline "它听出你说完 → 它开口" \
        --big "300ms" \
        --note "10 轮实测中位数 · 区间 238–429ms" \
        --foot "听出你说完本身还要约 0.5 秒"

未提供的行会跳过。所有行都自动缩字号以留出左右安全边距。
"""
from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
]

RATIOS = {
    "16:9": (16, 9, 1080),
    "9:16": (9, 16, 1920),
    "3:4": (3, 4, 1440),
    "4:5": (4, 5, 1440),
    "1:1": (1, 1, 1080),
    "5:6": (5, 6, 1260),
}


def find_font():
    for path, idx in FONT_CANDIDATES:
        if os.path.exists(path):
            return path, idx
    return None, 0


def load(path, idx, size):
    try:
        return ImageFont.truetype(path, size, index=idx)
    except Exception:
        return ImageFont.load_default()


def text_w(draw, s, font):
    b = draw.textbbox((0, 0), s, font=font)
    return b[2] - b[0]


def fit(draw, s, path, idx, size, max_w, min_size=18):
    """按需要缩小字号，直到宽度不超过 max_w。"""
    while size > min_size:
        f = load(path, idx, size)
        if text_w(draw, s, f) <= max_w:
            return f, size
        size -= 2
    return load(path, idx, min_size), min_size


def hex2rgb(v: str):
    v = v.lstrip("#")
    if v.startswith("0x"):
        v = v[2:]
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", default="3:4", help="16:9 / 9:16 / 3:4 / 4:5 / 1:1 / 5:6，或 W:H")
    ap.add_argument("--height", type=int, help="输出高度，默认按画幅取 1080/1440/1920")
    ap.add_argument("--width", type=int, help="直接指定宽度（覆盖 --ratio 计算）")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--line", help="第一行：小字、弱色（说明性质）")
    ap.add_argument("--headline", help="主标题：中号、常规色")
    ap.add_argument("--big", help="大数字：强调色")
    ap.add_argument("--note", help="大数字下方的补充（区间、条件）")
    ap.add_argument("--foot", help="最后一行：小字、弱色（注意事项）")
    ap.add_argument("--bg", default="0x111317")
    ap.add_argument("--fg", default="0xE8EAED")
    ap.add_argument("--muted", default="0x9AA0A6")
    ap.add_argument("--accent", default="0x3FCF8E")
    a = ap.parse_args()

    if a.ratio in RATIOS:
        rw, rh, dh = RATIOS[a.ratio]
    else:
        p = a.ratio.split(":")
        rw, rh, dh = float(p[0]), float(p[1]), 1440

    H = a.height or dh
    W = a.width or int(round(H * rw / rh / 2) * 2)

    font_path, font_idx = find_font()
    if not font_path:
        print("找不到中文字体，请在 FONT_CANDIDATES 里补一个路径", file=sys.stderr)
        return 2

    img = Image.new("RGB", (W, H), hex2rgb(a.bg))
    d = ImageDraw.Draw(img)

    margin = int(W * 0.08)          # 左右安全边距，手机上不被圆角/进度条吃掉
    max_w = W - 2 * margin
    m = min(W, H)

    # 字号：竖版内容更窄，小字按宽度而不是短边定，否则一行放不下
    base = min(m, int(W * 0.62))
    spec = [
        (a.line,     int(base * 0.048), hex2rgb(a.muted)),
        (a.headline, int(base * 0.086), hex2rgb(a.fg)),
        (a.big,      int(base * 0.300), hex2rgb(a.accent)),
        (a.note,     int(base * 0.044), hex2rgb(a.muted)),
        (a.foot,     int(base * 0.044), hex2rgb(a.muted)),
    ]
    items = []
    for text, size, color in spec:
        if not text:
            continue
        f, size = fit(d, text, font_path, font_idx, size, max_w)
        b = d.textbbox((0, 0), text, font=f)
        items.append({"text": text, "font": f, "color": color,
                      "w": b[2] - b[0], "h": b[3] - b[1], "size": size})

    if not items:
        print("至少要给一行文字", file=sys.stderr)
        return 2

    gap = int(m * 0.030)
    bar_h = max(3, int(m * 0.005))
    bar_w = int(m * 0.075)

    total = bar_h + sum(it["h"] for it in items) + gap * len(items)
    y = (H - total) // 2

    # 顶部强调条：唯一的视觉锚点
    d.rectangle([(W - bar_w) // 2, y, (W + bar_w) // 2, y + bar_h], fill=hex2rgb(a.accent))
    y += bar_h + gap

    for it in items:
        x = (W - it["w"]) // 2
        d.text((x, y - d.textbbox((0, 0), it["text"], font=it["font"])[1]), it["text"],
               font=it["font"], fill=it["color"])
        y += it["h"] + gap

    img.save(a.out)
    print(f"{a.out}  {W}x{H}  行数={len(items)}")
    for it in items:
        print(f"  字号 {it['size']:>3} 宽 {it['w']:>4}/{max_w}  {it['text'][:34]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
