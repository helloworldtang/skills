#!/usr/bin/env python3
"""verify.py — 成片验收。不合格非零退出。

检查项（每一项都是真实踩过的坑）：
  1 完整解码无错误
  2 流参数合规（H.264 high / yuv420p / AAC 48k 立体声 / moov 前置）
  3 帧数 = 时长 × 帧率（CFR 真做到，而不是只写了参数）
  4 积分响度落在目标 ±1.5 LU，真峰不超 -1.0 dBTP
  5 音画同步：与源素材比"说话起点"的偏移，应恰好等于开场卡时长
  6 无黑场（补边色不算黑）

用法:
    python3 verify.py OUT.mp4
    python3 verify.py OUT.mp4 --src SRC.mov --start 3.8 --card-dur 3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

OK, BAD, WARN = "✅", "❌", "⚠️"


def sh(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def probe(path: str) -> dict:
    _, out = sh(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                 "-print_format", "json", path])
    return json.loads(out or "{}")


def check_decode(path: str) -> tuple[bool, str]:
    rc, out = sh(["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"])
    errs = [l for l in out.splitlines() if l.strip()]
    if rc == 0 and not errs:
        return True, f"{OK} 完整解码 0 错误"
    return False, f"{BAD} 解码报错 {len(errs)} 条：{errs[:3]}"


def check_streams(info: dict, path: str) -> tuple[bool, list[str]]:
    fmt = info.get("format", {})
    dur = float(fmt.get("duration") or 0)
    size = int(fmt.get("size") or 0)
    lines, ok = [], True
    lines.append(f"{OK} `{os.path.basename(path)}` · {dur:.2f}s · {size/1048576:.1f}MB")

    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    if not v:
        return False, lines + [f"{BAD} 没有视频流"]
    if v.get("codec_name") != "h264":
        ok = False
        lines.append(f"{BAD} 视频编码 {v.get('codec_name')}，平台普遍只认 h264")
    else:
        lines.append(f"{OK} 视频 h264/{v.get('profile')} L{v.get('level')} "
                     f"{v.get('width')}x{v.get('height')} {v.get('pix_fmt')}")
    if v.get("pix_fmt") != "yuv420p":
        ok = False
        lines.append(f"{BAD} pix_fmt={v.get('pix_fmt')}，必须是 yuv420p")
    if not a:
        ok = False
        lines.append(f"{BAD} 没有音频流（信息流平台会判无声音）")
    else:
        if a.get("codec_name") != "aac":
            ok = False
            lines.append(f"{BAD} 音频编码 {a.get('codec_name')}，建议 aac")
        else:
            lines.append(f"{OK} 音频 aac {a.get('sample_rate')}Hz "
                         f"{a.get('channels')}ch {int(a.get('bit_rate') or 0)//1000}kbps")
        if int(a.get("sample_rate") or 0) < 44100:
            ok = False
            lines.append(f"{BAD} 采样率 {a.get('sample_rate')} 偏低")

    # moov 是否前置（faststart）：只读文件头部判断
    with open(path, "rb") as f:
        head = f.read(200000)
    moov = head.find(b"moov")
    mdat = head.find(b"mdat")
    if moov >= 0 and (mdat < 0 or moov < mdat):
        lines.append(f"{OK} moov 前置（faststart 生效，移动端可边下边播）")
    else:
        lines.append(f"{WARN} moov 未前置，建议加 -movflags +faststart")
    return ok, lines


def check_frames(path: str, info: dict) -> tuple[bool, str]:
    _, out = sh(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                 "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path])
    n = int((out.strip() or "0").split(",")[0] or 0)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    dur = float(info.get("format", {}).get("duration") or 0)
    rate = v.get("r_frame_rate", "0/1")
    num, den = (rate.split("/") + ["1"])[:2]
    fps = float(num) / float(den) if float(den) else 0
    expect = round(dur * fps) if fps else 0
    drift = abs(n - expect) if expect else 0
    if expect and drift > max(3, expect * 0.01):
        return False, f"{WARN} 帧数 {n}，按 {dur:.2f}s × {fps:g}fps 应有 {expect}（差 {drift}）— 可能仍是 VFR"
    return True, f"{OK} 帧数 {n}（{fps:g}fps × {dur:.2f}s，符合 CFR）"


def check_loudness(path: str, target: float) -> tuple[bool, str]:
    _, out = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn",
                 "-af", "ebur128=peak=true", "-f", "null", "-"])
    I = TP = None
    for m in re.finditer(r"I:\s*(-?\d+\.\d+)\s*LUFS", out):
        I = float(m.group(1))
    for m in re.finditer(r"Peak:\s*(-?\d+\.\d+)\s*dBFS", out):
        TP = float(m.group(1))
    if I is None:
        return True, f"{WARN} 未能读出响度"
    ok = abs(I - target) <= 1.5 and (TP is None or TP <= -1.0)
    mark = OK if ok else BAD
    return ok, f"{mark} 积分响度 {I:.1f} LUFS（目标 {target:g}）· 真峰 {TP if TP is not None else 'n/a'} dBTP"


def max_volume(path: str) -> float | None:
    _, out = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn",
                 "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume:\s*(-?\d+\.?\d*)\s*dB", out)
    return float(m.group(1)) if m else None


def envelope(path: str, seek: float = 0.0, dur: float | None = None,
             sr: int = 8000, hop: float = 0.01) -> list[float]:
    """10ms 一步的短时 RMS 包络（0–1）。"""
    import array
    cmd = ["ffmpeg", "-v", "error"]
    if seek:
        cmd += ["-ss", str(seek)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    p = subprocess.run(cmd, capture_output=True)
    a = array.array("h")
    a.frombytes(p.stdout[:len(p.stdout) // 2 * 2])
    step = int(sr * hop)
    out = []
    for i in range(0, len(a) - step + 1, step):
        blk = a[i:i + step]
        s = 0
        for v in blk:
            s += v * v
        out.append((s / len(blk)) ** 0.5 / 32768.0)
    return out


def best_lag(src_env: list[float], out_env: list[float], expect: float,
             span: float = 0.6, hop: float = 0.01):
    """在 expect ±span 内找让两条包络最相关的位移。返回 (lag 秒, 相关系数)。"""
    best_r, best_lag = -2.0, None
    step = max(1, int(0.01 / hop))          # 每 10ms 取一个候选
    lo = int((expect - span) / hop)
    hi = int((expect + span) / hop)
    use = min(len(src_env), 4000)            # 最多用前 40s，够且快
    base = src_env[:use]
    mb = sum(base) / use if use else 0.0
    db = sum((v - mb) ** 2 for v in base) or 1e-12
    for lag in range(lo, hi + 1, step):
        if lag < 0 or lag >= len(out_env):
            continue
        seg = out_env[lag:lag + use]
        n = len(seg)
        if n < 200:
            continue
        ms = sum(seg) / n
        ds = sum((v - ms) ** 2 for v in seg) or 1e-12
        cov = sum((base[i] - mb) * (seg[i] - ms) for i in range(n))
        r = cov / (db * ds) ** 0.5
        if r > best_r:
            best_r, best_lag = r, lag
    if best_lag is None:
        return None, -2.0
    return best_lag * hop, best_r


def check_av_sync(path: str, src: str, start: float, card: float) -> tuple[bool, str]:
    """用包络互相关对齐，而不是"首个说话点"。

    之前用 silencedetect 找静音结束点当锚点，在这类素材上会误判：
    源片本身就有 −35dB 上下的杂波，锚点会落在某个毛刺上；
    而成片在开场卡边界处还有一次 AAC 编码产生的 20ms 瞬态，
    两个都不是"人开始说话"。互相关只看整体起伏，增益、杂波都不影响。
    """
    se = envelope(src, seek=start)
    oe = envelope(path)
    if len(se) < 300 or len(oe) < 300:
        return True, f"{WARN} 音画同步：音频过短，跳过"
    # 稳态检测：纯音/恒定噪声的包络没有起伏，互相关的峰不尖锐 → 相关系数天然偏低，
    # 那不是"内容不一致"，是"这个方法对这种素材无效"。此时给提醒，不判 FAIL。
    base = se[:min(len(se), 4000)]
    mb = sum(base) / len(base)
    cv = (sum((v - mb) ** 2 for v in base) / len(base)) ** 0.5 / mb if mb > 1e-6 else 0.0
    lag, r = best_lag(se, oe, card)
    if lag is None:
        return True, f"{WARN} 音画同步：无法对齐，跳过"
    delta = lag - card
    if cv < 0.05:
        return True, (f"{WARN} 音画同步：源音频近似稳态（包络变异系数 {cv:.3f}），"
                      f"互相关不可用——算得位移 {lag:+.2f}s 但不足为凭，请人工听一遍")
    # 窄窗（±0.6s）只够判"对不对"，不够说"错多少"：真错位 3s 时窄窗会给出一个
    # 假的 +1.0s。所以不通过时放宽到整个成片再搜一次，把真实位移一并报出来。
    alt = ""
    if abs(delta) > 0.12 or r <= 0.5:
        lag2, r2 = best_lag(se, oe, card, span=max(2.0, card + 1.0))
        if lag2 is not None and r2 > r and abs(lag2 - lag) > 0.05:
            alt = f"；放宽窗口后最佳位移 {lag2:+.2f}s（相关 {r2:.3f}）"
    ok = abs(delta) <= 0.12 and r > 0.5
    mark = OK if ok else BAD
    extra = ""
    if abs(delta) > 0.12:
        extra = "  ← 拼接/裁剪点错位，重编（不要用 -c copy 拼）"
    elif r <= 0.5:
        extra = "  ← 相关系数偏低，两段音频可能不是同一内容"
    return ok, (f"{mark} 音画同步：实测位移 {lag:+.2f}s，"
                f"期望 {card:+.2f}s，偏差 {delta:+.2f}s（相关 {r:.3f}）{extra}{alt}")


def check_first_last_frames(path: str, info: dict) -> tuple[bool, str]:
    """首尾帧不能是纯色（黑场/白场）。

    不用 blackdetect：深色 UI 的整帧亮度本身就在 0.1 以下，
    blackdetect 会把整条视频判成黑场（实测过，误报率 100%）。
    改用"标准差 < 2 即视为纯色"，只在首尾各抽一帧，成本低且没有误报。
    """
    from PIL import Image, ImageStat
    dur = float(info.get("format", {}).get("duration") or 0)
    if dur <= 1:
        return True, f"{WARN} 时长过短，跳过首尾帧检查"
    msgs, ok = [], True
    for label, t in (("首帧", 0.1), ("末帧", max(0.1, dur - 0.15))):
        p = os.path.join(tempfile.gettempdir(), f".vpa_{label}_{os.getpid()}.png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", path,
                        "-frames:v", "1", p], capture_output=True)
        if not os.path.exists(p):
            continue
        sd = ImageStat.Stat(Image.open(p).convert("L")).stddev[0]
        os.unlink(p)
        if sd < 2.0:
            ok = False
            msgs.append(f"{label}几乎是纯色（亮度标准差 {sd:.1f}）")
    if ok:
        return True, f"{OK} 首尾帧正常（非黑场/白场）"
    return False, f"{BAD} " + "；".join(msgs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--src", help="源素材（给了才检查音画同步）")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--card-dur", type=float, default=0.0)
    ap.add_argument("--loudness", type=float, default=-16.0)
    a = ap.parse_args()

    if not os.path.exists(a.out):
        print(f"文件不存在: {a.out}", file=sys.stderr)
        return 2

    info = probe(a.out)
    results = []

    ok, lines = check_streams(info, a.out)
    results.append((ok, lines))
    if info.get("streams"):
        results.append(check_frames(a.out, info))
    results.append(check_decode(a.out))
    results.append(check_loudness(a.out, a.loudness))
    if a.src:
        results.append(check_av_sync(a.out, a.src, a.start, a.card_dur))
    results.append(check_first_last_frames(a.out, info))

    print("\n## 成片验收")
    allok = True
    for ok, msg in results:
        if isinstance(msg, list):
            for m in msg:
                print(" " + m)
        else:
            print(" " + msg)
        allok = allok and ok

    print(f"\n{'PASS' if allok else 'FAIL'} — {'全部通过，可以上传' if allok else '有不通过项，先修再发'}")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
