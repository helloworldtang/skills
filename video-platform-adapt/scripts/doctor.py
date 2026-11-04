#!/usr/bin/env python3
"""doctor.py — 一条命令回答"这台机器上还缺什么"。

这个 skill 本身是纯 Markdown + 四个脚本，**不需要 API key、账号、在线服务**。
它唯一的外部依赖是工具型的：ffmpeg（含 libx264）+ Pillow + 一个中文字体。

所以自检就是把这四样逐项验到底，并给每个失败项一条能直接抄的修复命令。

    python3 scripts/doctor.py
    python3 scripts/doctor.py --json          # 机器可读
    python3 scripts/doctor.py --no-smoke      # 跳过端到端编码（只查静态能力）

退出码：0 = 可用；1 = 有阻塞项。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# 必须存在的 filter。缺任何一个，probe/build/verify 都会在跑到一半时挂掉。
REQUIRED_FILTERS = [
    ("loudnorm", "两遍法响度归一化"),
    ("volumedetect", "测底噪，决定静音阈值"),
    ("silencedetect", "找起止点与片中静音"),
    ("ebur128", "成片响度验收"),
    ("anullsrc", "给开场卡配轨（否则卡段没音轨，拼接必错位）"),
]

OK, BAD, WARN, SKIP = "✅", "❌", "⚠️", "·"
results: list[dict] = []


def pad(s: str, width: int) -> str:
    """按显示宽度补空格——len() 对中文少算一半，直接 ljust 会错位。"""
    from unicodedata import east_asian_width
    w = sum(2 if east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(0, width - w)


def rec(name: str, status: str, detail: str = "", fix: str = "", blocking: bool = True) -> None:
    results.append({"item": name, "status": status, "detail": detail,
                    "fix": fix, "blocking": blocking and status == BAD})
    print(f"{status} {pad(name, 11)}{detail}")
    if status == BAD and fix:
        print(f"   ↳ 修：{fix}")


def sh(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    """ffmpeg 的诊断输出几乎全在 stderr，两条流都返回。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def first_line(text: str, keyword: str = "") -> str:
    for ln in text.splitlines():
        if keyword in ln:
            return ln.strip()
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def check_python() -> None:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 9):
        rec("python", OK, f"{ver}  {sys.executable}")
    else:
        rec("python", BAD, f"{ver}（脚本用了 3.9+ 的 list[str] 注解）",
            "装 3.9+ 并用它执行：python3.12 scripts/doctor.py")


def check_binary(name: str, req: str) -> bool:
    path = shutil.which(name)
    if not path:
        rec(name, BAD, "未找到", f"{req}")
        return False
    _, out = sh([name, "-version"])
    ver = first_line(out, f"{name} version").replace(f"{name} version ", "").split(" ")[0]
    rec(name, OK, f"{ver or '?'}  {path}")
    return True


def check_encoders(ffmpeg_ok: bool) -> None:
    if not ffmpeg_ok:
        rec("libx264", SKIP, "跳过（ffmpeg 未装）", blocking=False)
        return
    _, out = sh(["ffmpeg", "-hide_banner", "-encoders"])
    have = {ln.split()[1] for ln in out.splitlines()
            if len(ln.split()) > 1 and ln.startswith(" ")}
    missing = [e for e in ("libx264", "aac") if e not in have]
    if missing:
        rec("编码器", BAD, f"缺 {' / '.join(missing)}",
            "brew install ffmpeg（官方静态包一般带 libx264；"
            "Debian 需 ffmpeg 非 libav 的阉割包）")
    else:
        rec("编码器", OK, "libx264 + aac")


def check_filters(ffmpeg_ok: bool) -> None:
    if not ffmpeg_ok:
        rec("filters", SKIP, "跳过（ffmpeg 未装）", blocking=False)
        return
    _, out = sh(["ffmpeg", "-hide_banner", "-filters"])
    have = set()
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 3 and parts[2].count("->") == 1:
            have.add(parts[1])
    missing = [(f, why) for f, why in REQUIRED_FILTERS if f not in have]
    if missing:
        rec("filters", BAD, "缺 " + ", ".join(f for f, _ in missing),
            "换一个编译齐全的 ffmpeg 发行版（精简包常砍 loudnorm / ebur128）")
        for f, why in missing:
            print(f"   ↳ {f}：{why}")
    else:
        rec("filters", OK, " ".join(f for f, _ in REQUIRED_FILTERS))


def check_pillow() -> bool:
    try:
        import PIL
        from PIL import ImageFont
        ImageFont.load_default()  # 子模块真能用才算过（Pillow 装残缺时这一步会挂）
        rec("Pillow", OK, PIL.__version__)
        return True
    except Exception as e:  # noqa: BLE001
        rec("Pillow", BAD, f"import 失败：{e}",
            "python3 -m pip install --user pillow   # 或 uv pip install pillow")
        return False


def check_font(pillow_ok: bool) -> None:
    """字体是唯一的"环境资产型"依赖——不走网络、不带 key，但系统里未必有。"""
    if not pillow_ok:
        rec("中文字体", SKIP, "跳过（Pillow 未装）", blocking=False)
        return
    # 单一真源：字体候选表只在 card.py 里维护
    here = os.path.dirname(os.path.abspath(__file__))
    cands: list[tuple[str, int]] = []
    try:
        sys.path.insert(0, here)
        import card
        cands = list(card.FONT_CANDIDATES)
    except Exception:  # noqa: BLE001
        cands = [("/System/Library/Fonts/PingFang.ttc", 0)]

    hit = next(((p, i) for p, i in cands if os.path.exists(p)), None)
    if not hit:
        rec("中文字体", BAD, f"{len(cands)} 个候选路径全不存在",
            "装一套 CJK 字体（apt install fonts-noto-cjk），"
            "或把字体路径加进 scripts/card.py 的 FONT_CANDIDATES")
        return
    # 路径存在≠能渲染：.ttc 的 index 错了会抛，Pillow 会静默退回位图字体（中文变方块）
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(hit[0], 40, index=hit[1])
        w = f.getbbox("中")[2] - f.getbbox("中")[0]
        if w < 20:
            raise ValueError(f"\"中\"字宽 {w}px，疑似退回位图字体")
        rec("中文字体", OK, hit[0])
    except Exception as e:  # noqa: BLE001
        rec("中文字体", BAD, f"{hit[0]} 可用但渲染异常：{e}",
            "换一个 .ttc index（常见为 0/1）或另指一套字体")


def check_smoke(ffmpeg_ok: bool) -> None:
    """端到端最小闭环：合成 → libx264+aac 编码 → 完整解码。

    比任何静态检查都可靠：它同时验证了 lavfi、libx264、aac、movflags、以及写盘权限。
    """
    if not ffmpeg_ok:
        rec("端到端", SKIP, "跳过（ffmpeg 未装）", blocking=False)
        return
    tmp = tempfile.mkdtemp(prefix="vpa-smoke-")
    out = os.path.join(tmp, "smoke.mp4")
    t0 = time.time()
    rc, log = sh([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=0.5",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", out,
    ], timeout=90)
    if rc != 0:
        rec("端到端", BAD, f"编码失败 rc={rc}", first_line(log) or "看上面 ffmpeg 报错")
        shutil.rmtree(tmp, ignore_errors=True)
        return
    rc2, _ = sh(["ffmpeg", "-v", "error", "-i", out, "-f", "null", "-"], timeout=90)
    _, info = sh(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                  "-of", "csv=p=0", out])
    kinds = [k for k in info.replace("\n", ",").split(",") if k]
    ok = rc2 == 0 and "video" in kinds and "audio" in kinds
    detail = f"{time.time() - t0:.1f}s  流={'+'.join(k for k in kinds if k)}  解码={'干净' if rc2 == 0 else '出错'}"
    if ok:
        rec("端到端", OK, detail)
    else:
        rec("端到端", BAD, detail, "ffmpeg 能编码但产物不完整，换发行版重装")
    shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="video-platform-adapt 依赖自检")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-smoke", action="store_true", help="跳过端到端编码")
    a = ap.parse_args()

    print(f"video-platform-adapt 自检 · {time.strftime('%Y-%m-%d %H:%M')}")
    print("-" * 62)
    check_python()
    ff_ok = check_binary("ffmpeg", "brew install ffmpeg  /  apt install ffmpeg")
    fp_ok = check_binary("ffprobe", "随 ffmpeg 一起装（同一发行版）")
    check_encoders(ff_ok)
    check_filters(ff_ok)
    pil_ok = check_pillow()
    check_font(pil_ok)
    if a.no_smoke:
        rec("端到端", SKIP, "已跳过（--no-smoke）", blocking=False)
    else:
        check_smoke(ff_ok and fp_ok)
    print("-" * 62)

    blocked = [r for r in results if r["blocking"]]
    warns = [r for r in results if r["status"] == WARN]

    if a.json:
        print(json.dumps({"ok": not blocked and not warns, "blocked": blocked,
                          "warned": warns, "results": results}, ensure_ascii=False, indent=2))
    if blocked:
        print(f"结论：{len(blocked)} 项阻塞 —— 按上面的「修」补齐后再动手，"
              "否则 probe/build 会跑到一半才报错。")
        return 1
    if warns:
        print(f"结论：无阻塞，{len(warns)} 项提醒可忽略。")
        return 0
    print("结论：可用。下一步 python3 scripts/probe.py SRC.mov")
    return 0


if __name__ == "__main__":
    sys.exit(main())
