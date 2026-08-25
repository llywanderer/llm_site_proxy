# Skills description_zh Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** Store Chinese skill blurbs in `.skills-meta.json`, auto-generate on install (template + LLM), show in console.

**Architecture:** `skill_description_zh.py` generates text; `skill_meta_store` persists `descriptions_zh`; `enrich_skill_item` exposes `description_zh` / `description_display`; install hooks call `ensure_description_zh`.

**Tech Stack:** Python (bridge), React console, unittest.

## Global Constraints

- Do not rewrite `SKILL.md` description.
- Install must succeed even if LLM fails.
- `CURSOR_SKILLS_ZH_LLM` defaults to `1`.

---

### Task 1: Meta store + generator + tests

- [ ] Extend `skill_meta_store` with `descriptions_zh` getters/setters
- [ ] Add `skill_description_zh.py` (template + LLM + ensure/backfill)
- [ ] Unit tests for template, skip-if-exists, Chinese reuse

### Task 2: Install hook + API + enrich

- [ ] Hook `install_from_path` / `generate_skill` / delete cleanup
- [ ] Enrich list/get payloads; PATCH meta; backfill endpoint
- [ ] `.env.example` defaults

### Task 3: Console + backfill run

- [ ] Frontend prefer `description_display`
- [ ] Run backfill against `cursor_skills/`
