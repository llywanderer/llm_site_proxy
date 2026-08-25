# Skills 中文描述（description_zh）设计

日期：2026-08-23

## 目标

1. 为 `llm_site_proxy/cursor_skills/` 下全部已安装 skill 提供详细中文描述，供控制台展示。
2. 后续经 install / generate / upload 安装时自动生成。
3. **不修改** `SKILL.md` 原文 `description`（Agent 路由不变）。

## 决策

| 项 | 选择 |
|----|------|
| 存储 | `.skills-meta.json` → `descriptions_zh: { name: text }` |
| 生成 | 模板草稿 + LLM 润色（混合） |
| `CURSOR_SKILLS_ZH_LLM` | 默认 `1` |
| LLM 失败 | 保留模板；安装不失败 |
| 已有足够中文的 description | 直接采用（可轻截断），跳过 LLM |

## API 字段

每个 skill 项增加：

- `description_zh`：meta 中文（可空）
- `description_display`：`description_zh` 优先，否则 `description`

`PATCH /v1/skills/{name}/meta` 支持 `description_zh`。
`POST /v1/skills/descriptions-zh/backfill` 批量回填（`force?: bool`）。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `CURSOR_SKILLS_ZH_LLM` | `1` | LLM 润色 |
| `CURSOR_SKILLS_ZH_ON_INSTALL` | `1` | 安装后自动生成 |
| `CURSOR_SKILLS_ZH_TIMEOUT` | `60` | LLM 超时秒 |
| `CURSOR_SKILLS_ZH_LLM_URL` | 推导自 bridge 端口 | OpenAI 兼容 chat/completions |
| `CURSOR_SKILLS_ZH_LLM_MODEL` | `auto` | 模型名 |

## 成功标准

1. 现有 skill 均有可用中文（至少模板级）。
2. 新安装自动写入；LLM 挂掉不挡安装。
3. `SKILL.md` 不变；控制台显示中文。
