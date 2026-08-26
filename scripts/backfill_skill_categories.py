#!/usr/bin/env python3
"""为 cursor_skills 批量回填 LLM 推断分类（仅规则落到 other 的项）。

用法::

  CURSOR_SKILLS_DIR=../cursor_skills \\
    python3 scripts/backfill_skill_categories.py [--force] [--no-llm]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "macos_cursor_automation"
DEFAULT_SKILLS = ROOT / "cursor_skills"


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 Skills LLM 分类")
    parser.add_argument(
        "--skills-dir",
        default=os.environ.get("CURSOR_SKILLS_DIR") or str(DEFAULT_SKILLS),
        help="skills 根目录",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已有 inferred_by_name",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="不调用 LLM（仅跳过）",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="强制开启 LLM",
    )
    args = parser.parse_args()

    skills_dir = Path(args.skills_dir).expanduser().resolve()
    os.environ["CURSOR_SKILLS_DIR"] = str(skills_dir)
    if args.no_llm:
        os.environ["CURSOR_SKILLS_CATEGORY_LLM"] = "0"
    elif args.llm:
        os.environ["CURSOR_SKILLS_CATEGORY_LLM"] = "1"

    sys.path.insert(0, str(BRIDGE))
    from skill_category_llm import backfill_categories  # noqa: E402
    from skills_store import list_skills  # noqa: E402

    skills = list_skills(skills_dir)
    use_llm = False if args.no_llm else (True if args.llm else None)
    result = backfill_categories(skills, force=args.force, use_llm=use_llm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
