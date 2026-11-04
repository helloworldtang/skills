---
name: wechat-article-images
description: 公众号文章正文配图的 API 全链路——本地图片传微信永久素材拿 mmbiz URL，直接内嵌 Markdown 正文投递草稿箱。当用户要"文章带图 / 正文插图 / 配图进公众号 / 图片被微信过滤 / 外链图片不显示"时使用。含实测验证的接口契约与鉴权边界（2026-11-03 丹心文章三图实证）。
license: MIT
---

# 公众号文章正文配图（API 全链路）

> 实测验证：2026-11-03（丹心《扫码进来的人要等 10 秒》三张技术配图，经此链路全 API 进草稿箱并群发上线）。本 skill 的存在原因：公众号正文**外链图片会被过滤/不显示**，配图必须先变成微信素材（`mmbiz.qpic.cn` 域名）；而常见的认知误区是「素材库只能后台手动传」或「CLI 管道不支持图」——app 通道的上传接口一直在，只是没人从 CLI 侧用过。

## 触发时机

用户说「文章要配图 / 正文插图 / 图片进公众号 / 外链图不显示 / 投递带图文章」等；或走 exomind/wechat-publish 管道投递含图 Markdown 前。

## 核心认知（先读）

1. **正文图片必须是微信素材域名**（`https://mmbiz.qpic.cn/...`）。任意外链 URL（含自家 CDN）在草稿/群发环节会被微信过滤。
2. **两条通道别搞混**：
   - `POST /api/publish/admin/materials/upload`（admin 通道）——**只认 OIDC JWT**，CLI/API key 走不通（报「缺少 Authorization header」/「解析 JWT header 失败」）。
   - `POST /api/mp/materials/upload`（**app 通道**）——`x-api-key` 头鉴权，与 `/api/mp/publish` 同一把 key。**这是 CLI 侧唯一可用的口**。
3. 链路终点：上传返回的 mmbiz URL 直接写进 Markdown `![alt](mmbiz_url)`，走常规 markdown 直传投递（如 `exomind draft wechat <id> --account <号>`）——服务端渲染器把它当正文 image block 处理，与 yyps AI 配图的回填路径同构，**渲染端零改造**。

## 操作步骤

### 0. 前置自检（端到端跑通前先跑这个）

本 skill 驱动的是外部服务（yyps + 微信素材库），依赖**环境资产**（不随 skill 分发）。使用前逐项自检，缺哪项补哪项：

```bash
# ① API key 在位？（存放处各团队自定：常见于发稿脚本的 API_KEY 常量或密钥管理；
#    没有就向 yyps 服务的管理员索取——上传与发布共用同一把 app 通道 key）
echo "$YYPS_API_KEY" | grep -c . || grep -rc "API_KEY" <你的发稿脚本路径>

# ② yyps 服务可达？
curl -s -o /dev/null -w "%{http_code}\n" https://yyps.net/   # 期望 200/40x，超时=服务不可达

# ③ 目标号在上传白名单？（account 传错会在上传时报「未知账号」——也可直接跳到步骤 2 用小图试传验证）
```

技术图表依赖的 fireworks-tech-graph 是**独立 skill**（工具型依赖，引用不内联）：缺图能力时先装它，本 skill 只管「图 → 素材 → 正文」这一段。

### 1. 找 API key

yyps 的 app 通道 key 与 `/api/mp/publish` 投递 key 是同一把，由 yyps 服务管理员签发（各团队一般存在发稿脚本的 `API_KEY` 常量或环境变量 `YYPS_API_KEY`；**勿入库、勿写进任何会提交的文件**）。

### 2. 上传图片（每张一次调用，nonce 一次性）

```bash
TS=$(date +%s); EXP=$((TS+300)); NONCE=$(uuidgen | tr -d '-' | tr 'A-F' 'a-f')
curl -s -X POST "https://yyps.net/api/mp/materials/upload" \
  -H "x-api-key: <API_KEY>" \
  -F "account=<公众号 key，如 danxin>" \
  -F "file=@fig.png" \
  -F "nonce=$NONCE" -F "expires_at=$EXP"
```

返回：`{"success":true,"media_id":"...","url":"https://mmbiz.qpic.cn/...?wx_fmt=png"}`

**multipart 参数契约（缺一个都有专属报错，按报错补参）**：

| 字段 | 要求 |
|---|---|
| `account` | 目标公众号 key，素材挂在对应号的素材库 |
| `file` | 图片字节；mime 按扩展名定（png/gif/webp/jpeg 均支持） |
| `nonce` | 一次性随机串；重复用报「nonce 无效或已使用」 |
| `expires_at` | **epoch 秒**（服务端时刻），惯例 `now+300`；过期报「nonce 已过期」 |

### 3. 验证 URL（投递前必做）

```bash
curl -sIL "<mmbiz_url>" -o /dev/null -w "%{http_code} %{content_type}\n"   # 期望 200 image/png
```

### 4. 写进正文并投递

Markdown 里 `![说明](<mmbiz_url>)`，照常走投递管道。投递后在 mp 后台草稿箱**肉眼看一眼图是否显示**（首次在某号上用此链路时必看）。

## 已知坑

- **key 别进版本库**：skill/文档里只写 key 的存放路径，不写值。
- **macOS 系统 python3 打 HTTPS API 报 CERTIFICATE_VERIFY_FAILED**（缺 CA 老坑）——换 `curl --data-binary @file`，别折腾 python 证书。
- **AI 配图（`render-with-images`/`ai-image`）与手动传图是两条路**：前者是 yyps 服务端按 prompt 生成再上传，适合氛围图；本 skill 适合**精确的技术图表**（SVG/绘制脚本产出的 PNG）。
- 上传的是**永久素材**（占素材库容量），废弃图的 media_id 可经 `POST /api/mp/materials/list` 查到后由 admin 侧删除；日常量级无须清理。

## 配套：技术图表怎么来

若配图是架构/时序/数据流类技术图，先用 fireworks-tech-graph skill 出 SVG → PNG（几何校验 + 视觉走查），再走本 skill 上传。丹心文章的三张图（时序对比/数据流/证据链）即此组合：fireworks 出图 → zai 视觉走查 → 本 skill 传素材 → markdown 内嵌。

## 验证记录

- 2026-11-03：三张 PNG 经 app 通道上传全 success，mmbiz URL curl 200，markdown 直传投递丹心草稿箱，群发后线上正文三图正常显示。
