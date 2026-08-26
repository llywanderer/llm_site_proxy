# Skills 安装时 LLM 自动分类设计

日期：2026-08-25

## 目标

1. 新 skill 经 install / generate / upload 安装后，若现有规则会落到「其它」，则根据 description（及已有 `description_zh`）用 LLM 自动归类。
2. 立即回填当前已装且为「其它」的 skill。
3. **不修改** `SKILL.md`；不覆盖 Console 手动分类与 frontmatter / 命名规则。

## 决策

| 项 | 选择 |
|----|------|
| 分类方式 | LLM 从现有 category id 中选一 |
| 介入时机 | 仅当 frontmatter / 默认 by_name / 命名约定仍为 `other` |
| 存储 | `.skills-meta.json` → `inferred_by_name: { name: category_id }`（与 Console `by_name` 分离） |
| 优先级 | Console `by_name` → frontmatter → 默认表/命名规则 → `inferred_by_name` → `other` |
| 安装钩子 | 中文描述生成之后；失败不挡安装 |
| 回填 | CLI + `POST /v1/skills/categories/backfill`；实现后立刻跑一轮 |

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `CURSOR_SKILLS_CATEGORY_LLM` | `1` | 是否调用 LLM |
| `CURSOR_SKILLS_CATEGORY_ON_INSTALL` | `1` | 安装后自动推断 |
| LLM URL/model/timeout/key | 复用 `CURSOR_SKILLS_ZH_*` | 与中文描述同一通道 |

## API

- skill 项：`category_source` 可为 `llm:inferred`
- `POST /v1/skills/categories/backfill`：`{ force?: bool, use_llm?: bool }`

## 成功标准

1. 无 frontmatter/规则的新装 skill 多数不再落「其它」。
2. 已有正确分类不被改写；Console 手动分类仍最高优先。
3. LLM 失败保留 `other`，安装成功。

## 类目扩展（2026-08-25）

为覆盖 Unity/Unreal/固件等专长，默认目录增加：

- `engineering`（工程开发）
- `game`（游戏与引擎，含 XR）
