# skills

Agent skill 合集，按 **Agent Skills 标准约定**（目录 + `SKILL.md` + YAML frontmatter）编写。skill 本质是一份结构化 Markdown 操作规程，各环境按下表安装即用。

## Skills

| Skill | 说明 |
|---|---|
| [minigame-event-report](./minigame-event-report/) | 微信小游戏/小程序自定义事件（`wx.reportEvent`）在 We分析 的注册全流程：实测验证的操作路径、平台契约（属性全局唯一/默认属性/T+1）、事件与属性清单模板、新增埋点 checklist。 |

## 安装

先 clone：

```bash
git clone https://github.com/helloworldtang/skills.git
cd skills
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

## 使用

Claude Code 环境装好后，对话出现触发词（「注册事件」「埋点上报」「reportEvent 没数据」）自动加载，也可显式 `/minigame-event-report` 调用；其他环境由你或你的 agent 按上文方式挂载后引用。

## 约定

- 每个 skill 一个目录，入口为 `SKILL.md`（YAML frontmatter：`name` + `description`，`description` 写清触发时机）。
- skill 内容含**实测日期戳**的后台 UI 路径，界面漂移时以用户实际截图为准并回溯更新——欢迎提 PR 修正过时路径。
- 通用内容与项目专属数据分离：事件清单等资产以「模板 + 示例」形式提供，装走后替换成自己项目的数据。

## License

[MIT](./LICENSE)
