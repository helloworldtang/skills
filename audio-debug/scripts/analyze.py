#!/usr/bin/env python3
"""音频声爆检测 + 参考音包络互相关定位。

用法:
  analyze.py rec.wav                          # 只列声爆
  analyze.py rec.wav --ref ref.wav            # 对录音做参考音包络匹配
  analyze.py rec.wav --ss 9.0 --to 12.0       # 只分析时间窗（先粗看再放大）
  analyze.py rec.wav --threshold 0.004        # 手动包络阈值（默认按本底噪声自适应）

依赖: ffmpeg + numpy。输出口径: 10ms 包络分桶（1ms 窗平滑）。
注意: 与 ffmpeg silencedetect 阈值口径不一致，以本脚本包络结果为准。
互相关在包络域而非波形域:打击乐类短音的波形互相关对模板起点极敏感
(实测挪 8ms 相关系数 0.51→0.10),包络形状才是稳定特征。
"""
import argparse
import subprocess
import sys

import numpy as np

SR = 44100
ENV_SR = 1000  # 包络互相关工作采样率


def load(path: str, ss=None, to=None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", str(ss)]
    if to is not None:
        cmd += ["-to", str(to)]
    cmd += ["-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    out = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def envelope(x: np.ndarray) -> np.ndarray:
    """1ms 窗平滑包络（44.1kHz 采样率）。"""
    win = 44
    return np.convolve(np.abs(x), np.ones(win) / win, mode="same")


def envelope_1k(x: np.ndarray) -> np.ndarray:
    """重采样到 1kHz 的包络（互相关用；44100/1000 非整数须插值）。"""
    e = envelope(x)
    t_old = np.arange(len(e)) / SR
    t_new = np.arange(int(len(e) / SR * ENV_SR)) / ENV_SR
    return np.interp(t_new, t_old, e)


def auto_threshold(x: np.ndarray) -> float:
    """本底噪声估自整段录音的低分位（窗口内可能全是信号，不能只看窗口），
    乘 5 并设下限保护。"""
    env = envelope(x)
    return max(float(np.percentile(env, 25)) * 5, 0.0008)


def bursts(x: np.ndarray, thr: float, min_dur=0.02):
    env = envelope(x)
    above = env > thr
    out, s = [], None
    for i in range(len(above)):
        if above[i] and s is None:
            s = i
        elif not above[i] and s is not None:
            if (i - s) / SR >= min_dur:
                out.append((s / SR, i / SR))
            s = None
    if s is not None:
        out.append((s / SR, len(above) / SR))
    return out


def describe(x: np.ndarray, start, end):
    seg = x[int(start * SR):int(end * SR)]
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    fr = np.fft.rfftfreq(len(seg), 1 / SR)
    return np.abs(seg).max(), (sp * fr).sum() / max(sp.sum(), 1e-9)


def env_xcorr_hits(rec_env: np.ndarray, tmpl: np.ndarray, top=5):
    """包络域归一化互相关。返回 (t_s, r) 最强 top 个峰，200ms 内相邻峰归并。
    r∈[-1,1]；>=0.5 视为强匹配，0.3–0.5 弱匹配（结合声爆表人工判读）。"""
    t = tmpl - tmpl.mean()
    t_ss = float(t @ t)
    if t_ss < 1e-12:
        return []
    L = len(t)
    ones = np.ones(L)
    conv = np.convolve(rec_env, t[::-1], mode="valid")       # Σ e[i+j]·t[j]
    s1 = np.convolve(rec_env, ones, mode="valid")            # 窗口和
    s2 = np.convolve(rec_env ** 2, ones, mode="valid")       # 窗口平方和
    var = np.maximum(s2 - s1 ** 2 / L, 1e-18)
    rs = conv / np.sqrt(var * t_ss)
    order = np.argsort(rs)[::-1]
    clustered = []
    for i in order:
        tp = i / ENV_SR
        if clustered and min(abs(tp - c[0]) for c in clustered) < 0.2:
            continue
        clustered.append((tp, float(rs[i])))
        if len(clustered) >= top:
            break
    return sorted(clustered)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--ref")
    ap.add_argument("--ss", type=float)
    ap.add_argument("--to", type=float)
    ap.add_argument("--threshold", type=float)
    args = ap.parse_args()

    rec = load(args.wav, args.ss, args.to)
    full = rec if args.ss is None and args.to is None else load(args.wav)
    thr = args.threshold or auto_threshold(full)
    print(f"envelope threshold: {thr:.5f}")

    bs = bursts(rec, thr)
    if not bs:
        print("no bursts found; try --threshold lower")
        return
    print("\nbursts:")
    print(f"  {'start':>8s} {'dur_s':>6s} {'peak':>7s} {'centroid_Hz':>11s}")
    prev = None
    for s, e in bs:
        peak, cen = describe(rec, s, e)
        gap = f" (+{(s - prev) * 1000:.0f}ms)" if prev is not None else ""
        print(f"  {s:8.3f} {e - s:6.3f} {peak:7.3f} {cen:11.0f}{gap}")
        prev = e

    if args.ref:
        ref = load(args.ref)
        rb = bursts(ref, auto_threshold(ref))
        if not rb:  # 参考音录音较短时自适应可能失效，退固定低阈值
            rb = bursts(ref, 0.003)
        if not rb:
            print("\nref has no bursts above threshold")
            return
        # 模板取参考音里最响的声爆（首爆可能是环境噪声）；
        # 起点回退 30ms 包住起振瞬态，长度 200ms 覆盖多击结构（Pop 类 A+B 击 ≈150ms）
        rs, re_ = max(rb, key=lambda b: np.abs(ref[int(b[0] * SR):int(b[1] * SR)]).max())
        t0 = max(rs - 0.03, 0)
        tmpl = envelope_1k(ref)[int(t0 * ENV_SR):int(t0 * ENV_SR) + int(0.2 * ENV_SR)]
        print(f"\nenvelope xcorr vs ref (template {t0:.3f}s + 200ms):")
        for t, r in env_xcorr_hits(envelope_1k(rec), tmpl):
            print(f"  hit @ {t:.3f}s  r={r:.3f}")


if __name__ == "__main__":
    sys.exit(main())
