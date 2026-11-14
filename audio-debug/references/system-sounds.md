# macOS 系统音击数指纹表

生成方法：`/System/Library/Sounds/*.aiff` → 44.1kHz 单声道 → 10ms 包络分桶取峰 → 峰值 >40%
的连续桶归为一"击"，击与击间隔 >1 桶才算分开。"击数"= 主观可辨的独立打击感次数。

用途：录音里测得两个声爆间隔后，对照此表——**间距等于某文件内部击间距 = 那只是
一次播放**，不是代码播了两遍。

| 音效 | 击数 | 击间距 (ms) | 时长 (s) | 听感备注 |
|---|---|---|---|---|
| Bottle | 2 | 80 | 0.77 | 吹气+啵 |
| Frog | 2 | 30 | 0.72 | 紧凑双击 |
| Morse | 2 | 70 | 0.70 | 电报双击 |
| Pop | 2 | 60 | 1.63 | "啵啵"，调音量同款；确认音场景慎用 |
| Basso | 1 | - | 0.77 | 低沉单击 |
| Blow | 1 | - | 1.40 | 吹气单音 |
| Funk | 1 | - | 2.16 | 连续低鸣，系统默认 beep |
| Glass | 1 | - | 1.65 | 玻璃单击 |
| Hero | 1 | - | 1.06 | 单音 |
| Ping | 1 | - | 1.50 | 单音（包络有次级小起伏但不成击） |
| Purr | 1 | - | 0.76 | 连续 |
| Sosumi | 1 | - | 1.54 | 单音 |
| Submarine | 1 | - | 1.49 | 低鸣 |
| Tink | 1 | - | 0.56 | 干净短"叮"，50ms 衰减完；确认音推荐 |

再生命令（分析口径变化时重新生成）：

```bash
python3 - <<'PY'
import numpy as np, subprocess, glob
def load(p):
    return np.frombuffer(subprocess.run(['ffmpeg','-v','error','-i',p,'-f','f32le',
        '-ac','1','-ar','44100','-'],capture_output=True).stdout, dtype=np.float32)
for f in sorted(glob.glob('/System/Library/Sounds/*.aiff')):
    x = load(f)
    env = np.convolve(np.abs(x), np.ones(44)/44, mode='same')
    pk = [float(env[i:i+441].max()) for i in range(0, len(env), 441)]
    peak = max(pk); thr = 0.15 * peak
    hits, s, last = [], None, None
    for i, v in enumerate(pk):
        if v > thr:
            if s is None: s = i
            last = i
        elif s is not None and i - last > 1:
            hits.append((s, last)); s = None
    if s is not None: hits.append((s, last))
    strong = [h for h in hits if max(pk[h[0]:h[1]+1]) > 0.4 * peak]
    gaps = [round((strong[i+1][0]-strong[i][0])*10) for i in range(len(strong)-1)]
    print(f.split('/')[-1], len(strong), gaps)
PY
```

> macOS 版本更新可能增删/修改系统音文件，结论存疑时用上面脚本重新生成。
