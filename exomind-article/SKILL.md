---
name: exomind-article
description: 通过 ExoMind 写作引擎生成公众号文章（基于知识库素材 + 号调性），保存到草稿箱，可选投递公众号。当用户想用 ExoMind 写文章/博客/公众号稿/技术科普时使用。
---

# ExoMind 公众号文章写作

ExoMind 的 content_engine 基于**知识库素材 + 公众号调性（writing profile）**生成文章草稿。前提：对应主题的知识已摄入 ExoMind（先 ingest 素材，再写文章质量更高）。

**前置依赖（工具型，不内联）**：`exomind` CLI（Node 瘦客户端，`npm i -g exomind` 或 `exomind install` 装好 Claude Code 配套）+ 可达的 ExoMind 服务端。无 CLI 时本 skill 不可用。

## 一键生成（exomind draft new）

```bash
exomind draft new "<topic>" --account <ailang|danxin|mingdeng>
```
- **topic**：文章主题/角度。**越具体、越毒舌越好**（例："用了3年 MCP 都不知道服务端其实跑在客户端本机"）——引擎据此 + 知识库 + 号调性生成标题与正文。
- **--account**：`danxin` / `ailang`（技术深度）/ `mingdeng`。可省略（router 按选题推荐，看输出 `recommended_account`）。
- `new` = 生成（POST /generate-draft）+ 保存（POST /drafts）两步合一，打印 draft id + 复核地址。
- ⏳ 服务器 LLM 生成 1-3 分钟；遇并发限流自动 sleep 重试（cli 内置）。

## 草稿管理

- `exomind draft list` — 草稿列表（`--status published` 过滤已存档）
- `exomind draft show <id>` — 草稿详情（正文 / 标题候选 / 推荐号）
- `exomind draft publish <id>` — 存档到知识库（抽取实体）
- `exomind draft wechat <id> --account <号>` — 投递公众号草稿箱（**不群发**，用户在公众号后台手动发）

## 必读坑

- **account 要是已注册号**（danxin/ailang/mingdeng），否则 router 按选题关键词路由到别的号（看 `recommended_account` + `routing_reason` 确认）。
- 草稿质量看 `confidence` + `pitfalls_count`；不满意改 topic 重生成（非确定性，每次略不同）。
- 复核网页：`{base_url}/ui/drafts` 按 id 找草稿。
- **参考链接必须以明文 URL 写进正文**（2026-09-21 实测教训：URL 只放 `sources` 元数据则公众号正文零链接）。公众号正文不支持外部超链接，md 的 `[标题](URL)` 投到草稿箱会被过滤/不可点；正解是参考段写成「来源名 + 空格 + 明文 URL」一行一条（例：`- TypeSafe 官方博客 https://typesafe.ai/blog/...`），读者复制可用。投递前逐条核对 URL 已在正文且实测可达。

## 与其他写作 skill 的关系

- 本 skill 是「知识库素材充足、要快速起稿」的通道；成文后的人工协作打磨走 `article-coauthoring`，发布前门禁走 `article-deslop`（引擎稿必手术的通用版）。
