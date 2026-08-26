"""skill_category_llm / inferred taxonomy 单元测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class SkillCategoryLlmTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        skills = Path(self._td.name) / "skills"
        skills.mkdir()
        os.environ["CURSOR_SKILLS_DIR"] = str(skills)
        os.environ.pop("CURSOR_SKILLS_META_PATH", None)
        os.environ["CURSOR_SKILLS_CATEGORY_LLM"] = "1"
        os.environ["CURSOR_SKILLS_CATEGORY_ON_INSTALL"] = "1"
        os.environ["CURSOR_SKILLS_ZH_ON_INSTALL"] = "0"
        os.environ["CURSOR_SKILLS_ZH_LLM"] = "0"

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_needs_inferred_when_other(self) -> None:
        from skill_taxonomy import needs_inferred_category

        self.assertTrue(needs_inferred_category("weird-unknown-tool"))
        self.assertFalse(needs_inferred_category("remotion-create"))
        self.assertFalse(
            needs_inferred_category(
                "x",
                frontmatter={"category": "content"},
            )
        )

    def test_inferred_persists_and_enriches(self) -> None:
        from skill_category_llm import ensure_inferred_category
        from skill_meta_store import get_inferred_category
        from skill_taxonomy import categorize_skill

        def fake_llm(*_a, **_k):
            return "content"

        hit = ensure_inferred_category(
            "poster-maker-xyz",
            description="Generate cinematic poster illustrations for articles",
            llm_fn=fake_llm,
        )
        self.assertEqual(hit, "content")
        self.assertEqual(get_inferred_category("poster-maker-xyz"), "content")
        tax = categorize_skill("poster-maker-xyz")
        self.assertEqual(tax["category"], "content")
        self.assertEqual(tax["category_source"], "llm:inferred")

    def test_rules_skip_llm(self) -> None:
        from skill_category_llm import ensure_inferred_category
        from skill_meta_store import get_inferred_category

        calls = {"n": 0}

        def fake_llm(*_a, **_k):
            calls["n"] += 1
            return "utility"

        hit = ensure_inferred_category(
            "andrej-karpathy-perspective",
            description="Karpathy thinking framework",
            llm_fn=fake_llm,
        )
        self.assertIsNone(hit)
        self.assertIsNone(get_inferred_category("andrej-karpathy-perspective"))
        self.assertEqual(calls["n"], 0)

    def test_console_override_beats_inferred(self) -> None:
        from skill_meta_store import set_inferred_category, set_skill_category
        from skill_taxonomy import categorize_skill

        set_inferred_category("demo-skill", "content")
        set_skill_category("demo-skill", "docs")
        tax = categorize_skill("demo-skill")
        self.assertEqual(tax["category"], "docs")
        self.assertEqual(tax["category_source"], "meta:by_name")

    def test_install_hook_categorizes(self) -> None:
        from skill_category_llm import maybe_categorize_on_install
        from skill_meta_store import get_inferred_category

        # patch classify via ensure by setting env and monkey via module
        import skill_category_llm as mod

        orig = mod.classify_category_llm

        def fake_llm(*_a, **_k):
            return "publish"

        mod.classify_category_llm = fake_llm  # type: ignore
        try:
            item = maybe_categorize_on_install(
                {
                    "name": "weibo-blast",
                    "description": "Post threads to Weibo and X",
                    "category": "other",
                    "description_zh": "把内容发布到微博",
                }
            )
        finally:
            mod.classify_category_llm = orig  # type: ignore
        self.assertEqual(get_inferred_category("weibo-blast"), "publish")
        self.assertEqual(item.get("category"), "publish")

    def test_backfill_updates(self) -> None:
        from skill_category_llm import backfill_categories

        def fake_llm(name, **_k):
            return "docs" if "summary" in name else "utility"

        result = backfill_categories(
            [
                {
                    "name": "article-summary-bot",
                    "description": "Summarize long documents",
                },
                {
                    "name": "remotion-create",
                    "description": "Create Remotion video",
                },
            ],
            use_llm=True,
            llm_fn=fake_llm,
        )
        self.assertIn("article-summary-bot", result["updated"])
        self.assertIn("remotion-create", result["skipped"])


if __name__ == "__main__":
    unittest.main()
