# skills

Agent skill 合集，按 **Claude Code skill 标准**（Anthropic Agent Skills 约定：目录 + `SKILL.md` + YAML frontmatter）编写。

**不只是 Claude Code 能用**：skill 本质是一份 Markdown 操作规程——Claude Code 装入 `~/.claude/skills/` 后可按触发词自动加载；其他 AI 助手（Cursor / Codex / 任意 agent）把 `SKILL.md` 挂进自己的规则/提示体系同样可用，只是没有自动加载机制。

## Skills

| Skill | 说明 |
|---|---|
| [minigame-event-report](./minigame-event-report/) | 微信小游戏/小程序自定义事件（`wx.reportEvent`）在 We分析 的注册全流程：实测验证的操作路径、平台契约（属性全局唯一/默认属性/T+1）、事件与属性清单模板、新增埋点 checklist。 |

## 安装

**方式一：拷贝安装（最简单）**

```bash
# 整个 skill 目录拷到你的全局 skill 目录
cp -r minigame-event-report ~/.claude/skills/
```

装完即生效（新会话自动识别），说「注册事件 / 埋点上报」即可触发，或手动 `/minigame-event-report`。

**方式二：软链（想跟进更新）**

```bash
git clone https://github.com/helloworldtang/skills.git
ln -s "$(pwd)/skills/minigame-event-report" ~/.claude/skills/minigame-event-report
```

**方式三：项目级安装**（只对某个仓库生效）

```bash
cp -r minigame-event-report <你的项目>/.claude/skills/
```

## 使用

安装后无需任何配置。对话中出现触发词（如「注册事件」「埋点上报」「reportEvent 没数据」）时 Claude 会自动加载对应 skill；也可以显式输入 `/skill名` 调用。

## 约定

- 每个 skill 一个目录，入口为 `SKILL.md`（YAML frontmatter：`name` + `description`，`description` 写清触发时机）。
- skill 内容含**实测日期戳**的后台 UI 路径，界面漂移时以用户实际截图为准并回溯更新——欢迎提 PR 修正过时路径。
- 通用内容与项目专属数据分离：事件清单等资产以「模板 + 示例」形式提供，装走后替换成自己项目的数据。

## License

[MIT](./LICENSE)
