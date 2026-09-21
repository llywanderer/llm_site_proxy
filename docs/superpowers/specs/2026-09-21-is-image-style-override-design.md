# is_image_style 三态覆盖设计

**日期：** 2026-09-21  
**状态：** implemented  
**范围：** `llm_site_proxy`（bridge + proxy_console）

## 背景

`is_image_style` 由 `skill_preview.is_image_style_skill()` 自动推断。名称 hint 不完全（如 `handdraw` vs `hand-drawn`）会导致真实生图 skill 进不了工厂「生图 Skills」下拉。需要可写、可清除的覆盖入口。

## 目标

1. 支持三态：强制是 / 强制否 / 回退自动推断  
2. Bridge API + Console Skills 页均可设置  
3. **meta 覆盖优先级最高**，可压过名称硬排除与类目硬排除  
4. 列表返回足够字段，供 UI 编辑与下游过滤

## 非目标

- 不改 `_NAME_HINTS` 补洞（可用本覆盖解决个案）  
- 设为 `true` 后不自动触发预览生成（沿用现有 ensure / backfill）  
- 不改 vtok_ai_factory 过滤逻辑（仍认 bridge 返回的 `is_image_style`）

## 存储

文件：`.skills-meta.json`（与现有 category/tags 同文件）

新增字段：

```json
{
  "is_image_style_by_name": {
    "handdraw-style-prompter": true,
    "some-skill": false
  }
}
```

- key 存在 → 强制覆盖（`true` / `false`）  
- key 不存在 → 自动推断  
- skill 卸载时：与 category/tags 一样清理对应 key（若已有卸载清理钩子则一并清理）

## 判定优先级

在 `attach_preview_fields`（或等价列表 enrich 点）最终写入 `is_image_style`：

1. **若** `get_is_image_style_override(name)` 返回 `bool` → 用之，`is_image_style_source = "meta"`  
2. **否则** → `is_image_style_skill(...)`，`is_image_style_source = "auto"`

硬排除（perspective / remotion / 工程类目等）仅作用于 auto 路径；meta 可强制 `true`。

## 列表/详情字段

| 字段 | 类型 | 含义 |
|------|------|------|
| `is_image_style` | bool | 生效值（下游过滤用） |
| `is_image_style_source` | `"meta"` \| `"auto"` | 来源 |
| `is_image_style_override` | `true` \| `false` \| `null` | 原始覆盖；`null` = 无覆盖 |

`preview_*` 仍按生效后的 `is_image_style` 计算。

## Bridge API

扩展现有 `PATCH /v1/skills/{name}/meta`：

| 字段 | 行为 |
|------|------|
| `is_image_style: true \| false` | 写入覆盖 |
| `clear_is_image_style: true` | 删除覆盖，回退 auto |

冲突：若同时传 `clear_is_image_style` 与 `is_image_style`，**以 clear 为准**（与 `clear_category` 同风格）。

`skill_meta_store` 新增：

- `get_is_image_style_override(name) -> bool | None`  
- `set_is_image_style_override(name, value: bool | None)`  
- `patch_skill_meta(... is_image_style=..., clear_is_image_style=...)`

`load` / `_empty_doc` 识别并默认 `is_image_style_by_name: {}`。

## Console

1. **proxy 透传**：现有 `patch_skill_meta` 已转发 body，无需新路由；确认前端类型含新字段即可。  
2. **Skills 详情**：分类旁增加三态控件  
   - 自动（`null` → `clear_is_image_style`）  
   - 强制是（`is_image_style: true`）  
   - 强制否（`is_image_style: false`）  
3. 「保存分类/标签」一并提交该字段；强制「是」时可用弱提示：硬排除类 skill 也会进入生图栏。  
4. 列表可选用 badge 显示「覆盖」，非必须。

## 测试

- meta `true` → `is_image_style=true`，`source=meta`（含名称含 perspective 的用例）  
- meta `false` → 即使名称命中 hint 也为 `false`  
- clear → 回到 auto  
- `PATCH /meta` 往返  
- Console：类型与保存 payload 含新字段（若有前端测则补；无则手工验收）

## 验收

1. 对 `handdraw-style-prompter` 设 `is_image_style: true` 后，`GET /v1/skills` 该项为 `true` / `meta`  
2. 工厂生图 Skills 下拉出现该 skill（无需改工厂）  
3. clear 后恢复 auto（当前应为 `false`，因 hint 不匹配）  
4. Console 三态可保存并刷新展示
