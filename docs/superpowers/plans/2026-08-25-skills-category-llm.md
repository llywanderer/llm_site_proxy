# Skills LLM 自动分类实现计划

日期：2026-08-25

## 已完成

1. `skill_meta_store`：新增 `inferred_by_name` 读写
2. `skill_taxonomy`：优先级加入 `llm:inferred`；`needs_inferred_category`
3. `skill_category_llm`：单条 + 批量 LLM；安装钩子；回填
4. `maybe_generate_on_install` 末尾调用分类
5. `POST /v1/skills/categories/backfill` + `scripts/backfill_skill_categories.py`
6. 单测；对 `cursor_skills` 已跑回填

## 部署注意

- 代码已 `docker cp` 进 `cursor-openai-bridge`，**进程未重启**时安装 API 仍是旧逻辑
- 需你同意后 `docker restart cursor-openai-bridge` 才使安装钩子与 backfill API 生效
- meta 文件在挂载卷上，回填结果已立即可被列表逻辑读取（重启后 enrich 用新 taxonomy 代码）
