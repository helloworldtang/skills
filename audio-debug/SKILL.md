---
name: audio-debug
description: macOS UI 音效排障：当用户报告"响了两声/声音像回音/音效不对/多了一声 beep/没出声"，或需要确认某次操作到底播放了几个声音、每个声来自哪里时使用。方法为麦克风录音 + 包络/互相关波形分析 + 系统音击数指纹表，可在不改动目标应用代码的情况下定位声源。覆盖 NSSound/NSBeep/afplay 类问题。
license: MIT
agent_created: true
---

# macOS UI 音效排障：录音 + 波形分析定位声源

## 核心认知（先读，避免走弯路）

**"听起来响了两声"≠代码播放了两次。** 先按以下决策树分流，别急着怀疑事件双触发：

```
静态数调用点（grep NSSound / NSBeep / AVAudioPlayer / afplay）
│
├─ 声爆数 == 代码调用次数
│   → 大概率是【音效文件本身是多击结构】
│     查 references/system-sounds.md 指纹表：击间距对上文件内部结构 = 实锤
│     （实证案例：Pop.aiff 本身是 0ms/60ms 双击，一次播放听感就是"两声 beng 回音"）
│
└─ 声爆数 > 代码调用次数
    → 存在第二个声源，查系统 beep：
      · 关窗/拆窗时机在事件周期内 → AppKit 补 NSBeep（修法：拆窗推迟一 runloop）
      · orphan 事件（窗口关闭后 keyUp/mouse 事件无处投递）
      · 隔离验证用 minimal-repro skill 的复刻装置排除机制嫌疑
```

**多击结构音效速查**（完整表在 references/system-sounds.md）：
Pop（双击 60ms）、Bottle（双击 80ms）、Frog（双击 30ms）、Morse（双击 70ms）。
单击干净的：Tink、Basso、Blow、Funk（连续低鸣）、Glass、Hero、Ping、Purr、Sosumi、Submarine。

## 四步流程

### 1. 静态排查

```bash
grep -rn 'NSSound\|NSBeep\|AVAudioPlayer\|afplay\|\.play()' Sources/ --include='*.swift'
```

数清实际执行路径上有几次播放调用。只有一处 → 直接跳到第 3 步验文件结构。

### 2. 录音复现

关键技巧：**参考音必须用 afplay 在同一环境放出来录进麦**，不能拿系统里的干净文件直接做模板——扬声器+麦克风链路会改变波形，干净模板匹配率上不去（实测 r 从 0.86 掉到 0.5x）。

```bash
# scripts/record.sh：<秒数> [输出文件]
# 后台起 ffmpeg 录麦，同时 afplay 参考音（Pop/Funk 等目标嫌疑音），打印时间戳
```

与用户配合的时机卡位：录音窗口有限（10–30s），**用提问卡住流程**——先起录音，立刻发一个"请现在复现"的确认问题，用户操作完回来选确认，录音和分析正好衔接。

麦克风权限：新的终端进程首次录制会触发授权弹窗，失败时输出全静音（检查音轨 RMS ≈ -60dB 即未授权）。

### 3. 声爆检测与归类

```bash
# scripts/analyze.py <录音.wav> [--ref 参考音.wav]
# 输出：声爆列表（起点/时长/峰值/谱质心）+ 与参考音的互相关峰值位置
```

分析口径：
- 10ms 包络（1ms 窗平滑），阈值按本底噪声的 3–5 倍临场调（先 volumedetect 看 mean_volume）；
- **不要用 ffmpeg silencedetect 的阈值对照包络阈值**——两者口径不一致（实测 -38dB silencedetect 报的"非静音"和 0.004 包络阈值结果不同），以 numpy 包络为准；
- 互相关模板匹配用归一化互相关（normalize xcorr），hop 10ms，r>0.5 视为命中。

### 4. 判读

| 观察 | 结论 |
|---|---|
| 声爆数 = 调用数，击间距 = 指纹表某文件的内部击间距 | 单次播放，音放选错，换单击结构音效 |
| 声爆数 > 调用数，第二声谱质心明显偏低/更长 | 系统 beep（NSBeep/Funk 类），查关窗时机/orphan 事件 |
| 互相关只命中一次参考音 | 只播了一次，第二声另有来源 |
| 完全无声爆 | 播放失败（音量/输出设备/NSSound 实例未持有被提前释放） |

## 已知坑

- **zsh 的 `log` 是内建命令**，抓系统日志要写 `/usr/bin/log stream`；
- zsh 里 `echo "== x =="` 的 `=x` 触发 =cmd 路径展开，报 `= not found`；
- 录音里物理点击（鼠标/键盘）也是声爆，通常更短（<35ms）更尖，注意与音效区分；
- 环境噪声大时（人声/空调），先看 volumedetect 再定阈值，别硬套经验值。

## 依赖

- ffmpeg（brew，含 avfoundation 设备）
- python3 + numpy
- 仅 macOS（avfoundation 录音、/System/Library/Sounds 路径）
