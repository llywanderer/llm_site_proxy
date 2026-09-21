# Skill 生图预览设计

**日期：** 2026-09-20  
**状态：** approved → implementing

## 目标

生图 Skill 靠名字无法判断画风。在 `llm_site_proxy` 统一生成并托管预览图，经 API 供给 Studio / 公众号 / Console；新安装的生图 Skill 自动补图。

## 架构

- 资产：`{CURSOR_SKILLS_DIR}/{name}/preview.png`
- 列表：`GET /v1/skills` 增加 `has_preview` / `preview_status` / `preview_url` / `is_image_style`
- 取图：`GET /v1/skills/{name}/preview`
- 补图：`POST /v1/skills/{name}/preview/ensure`；`POST /v1/skills/previews/backfill`
- 安装钩子：install / upload / generate 成功后，若为生图类则异步 ensure
- 样张来源：已有 `examples/` 等图则拷贝；否则固定 prompt + 该 skill 生图

## 过滤收紧

- `game` / `other` 的 `purposes` 去掉 `image`，避免混进生图下拉
- `is_image_style`：category ∈ {content, generation} 或 tag `image`，或名称命中 illustration/poster/comic 等

## 下游

- 透传 preview 字段；代理预览图路由
- 生图选型改为缩略图网格
