# skills

Agent skill 合集，按 **Agent Skills 标准约定**（目录 + `SKILL.md` + YAML frontmatter）编写。skill 本质是一份结构化 Markdown 操作规程，各环境按下表安装即用。

## Skills

| Skill | 说明 |
|---|---|
| [problem-driven-article](./problem-driven-article/) | 技术问题解决型分享文的九段叙事结构：围绕一个具体问题点用假设/方案递进链推进，而非平铺知识点。含单一中心三律（一篇文章一个中心问题/概念黑箱化/陌生概念预算）、标题判据（不剧透答案、数字必兑现）、写作红线（实测值不冒充、安全网不是效果证据）。 |
| [article-coauthoring](./article-coauthoring/) | 成文写作的协作流程三关：挖料（info dump + 补洞问题）→ 逐节选材后写（先圈选内容点再动笔，反馈即学偏好）→ 盲测验收（零上下文 sub-agent 只读成稿答读者问题，抓"作者以为讲清了其实没讲清"）。管写作推进过程，文体骨架引用结构 skill。 |
| [article-deslop](./article-deslop/) | 中文文章发布前的去 AI 腔门禁，三层递进：确定性四规则（套话密度>5处/千字、开头套路五前缀、句长变异系数<0.35、连续三段同首词）+ 审稿四问（活人思考/信息增益/对话感/共鸣入口）+ 写作红线拦截。只统计散文防误伤，只提醒不阻断，改不改作者拍板。 |
| [minigame-event-report](./minigame-event-report/) | 微信小游戏/小程序自定义事件（`wx.reportEvent`）在 We分析 的注册全流程：实测验证的操作路径、平台契约（属性全局唯一/默认属性/T+1）、事件与属性清单模板、新增埋点 checklist。 |
| [wechat-article-images](./wechat-article-images/) | 公众号文章正文配图的 API 全链路：本地图片经 yyps app 通道传微信永久素材拿 mmbiz URL，直接内嵌 Markdown 投递草稿箱；含 multipart 参数契约（nonce/expires_at）、admin 与 app 通道鉴权边界、外链图被过滤的根因。 |
| [video-platform-adapt](./video-platform-adapt/) | 一条录屏 → 视频号 / 小红书 / B站可直发成片：素材体检（VFR、响度、尾部录制事故、黑边）、裁切取舍、两遍法响度归一化、开场卡、六项成片验收。带四个脚本 + `doctor.py` 自检，纯本地、无 API key。 |

## 安装

先 clone：

```bash
git clone https://github.com/helloworldtang/skills.git
cd skills
```

**WorkBuddy / 通用 skill 目录（推荐软链，改仓库即生效）**

```bash
ln -s "$(pwd)/video-platform-adapt" ~/.workbuddy/skills/video-platform-adapt
```

**Claude Code（全局，触发词自动加载）**

```bash
cp -r minigame-event-report ~/.claude/skills/
# 或软链跟进更新：ln -s "$(pwd)/minigame-event-report" ~/.claude/skills/minigame-event-report
```

**Claude Code（项目级，只对该仓库生效）**

```bash
cp -r minigame-event-report <你的项目>/.claude/skills/
```

**Cursor**

```bash
# 放入项目规则目录，Cursor 会随项目加载
cp minigame-event-report/SKILL.md <你的项目>/.cursor/rules/minigame-event-report.md
```

**其他 AI 助手 / 任意 agent**

`SKILL.md` 就是普通 Markdown，两条路任选：
- 把文件内容粘进你所用工具的 system prompt / 自定义指令
- 作为项目文档放仓库里，对话中让 agent 「按 docs/minigame-event-report/SKILL.md 的流程执行」

带 `scripts/` 的 skill（如 `video-platform-adapt`）安装后先跑自检，缺什么一目了然：

```bash
python3 ~/.workbuddy/skills/video-platform-adapt/scripts/doctor.py
# 想确认不只是依赖在、链路真的通（用合成素材跑一遍，约 20 秒）：
python3 ~/.workbuddy/skills/video-platform-adapt/scripts/doctor.py --demo
```

## 使用

Claude Code 环境装好后，对话出现触发词（「注册事件」「埋点上报」「reportEvent 没数据」）自动加载，也可显式 `/minigame-event-report` 调用；其他环境由你或你的 agent 按上文方式挂载后引用。

## 约定

- 每个 skill 一个目录，入口为 `SKILL.md`（YAML frontmatter：`name` + `description`，`description` 写清触发时机）。
- skill 内容含**实测日期戳**的后台 UI 路径，界面漂移时以用户实际截图为准并回溯更新——欢迎提 PR 修正过时路径。
- 通用内容与项目专属数据分离：事件清单等资产以「模板 + 示例」形式提供，装走后替换成自己项目的数据。
- **自包含边界**：知识型依赖（接口契约、参数表、坑）内联在 skill 里；工具型依赖（ffmpeg、curl、别的 skill）只声明版本与来路，**不内联本体**；环境资产（服务地址、API key、账号）**一律不进仓**，只写存放路径。
- **自检可诊断**：带 `scripts/` 的 skill 必须提供一条自检命令，标准是「装完跑一条命令就知道缺什么、卡在哪」，而不是「装了就跑」。典范见 `video-platform-adapt/scripts/doctor.py`。

## License

[MIT](./LICENSE)
