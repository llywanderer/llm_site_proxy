"""skill_description_zh 单元测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class SkillDescriptionZhTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        skills = Path(self._td.name) / "skills"
        skills.mkdir()
        os.environ["CURSOR_SKILLS_DIR"] = str(skills)
        os.environ.pop("CURSOR_SKILLS_META_PATH", None)
        os.environ["CURSOR_SKILLS_ZH_LLM"] = "0"
        os.environ["CURSOR_SKILLS_ZH_ON_INSTALL"] = "1"

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_draft_known_remotion(self) -> None:
        from skill_description_zh import draft_description_zh, looks_chinese

        text = draft_description_zh("remotion-create", description="Create a Remotion video")
        self.assertTrue(looks_chinese(text))
        self.assertIn("BookTok", text)

    def test_reuse_chinese_description(self) -> None:
        from skill_description_zh import draft_description_zh

        src = (
            "Paul Graham的思维框架与表达方式。"
            "用途：作为创业顾问，用PG的视角分析创业、写作与产品选择。"
        )
        text = draft_description_zh(
            "paul-graham-perspective",
            description=src,
            display_name="paul-graham",
        )
        self.assertIn("Paul Graham", text)
        self.assertIn("创业顾问", text)

    def test_ensure_persists_and_skips(self) -> None:
        from skill_description_zh import ensure_description_zh
        from skill_meta_store import get_description_zh

        first = ensure_description_zh(
            "baoyu-cover-image",
            description="Generates article cover images",
            category="content",
            category_label="内容创作",
            use_llm=False,
        )
        self.assertTrue(first)
        self.assertEqual(get_description_zh("baoyu-cover-image"), first)
        second = ensure_description_zh(
            "baoyu-cover-image",
            description="changed",
            use_llm=False,
            force=False,
        )
        self.assertEqual(second, first)

    def test_llm_fallback_keeps_draft(self) -> None:
        from skill_description_zh import ensure_description_zh

        def boom(*_a, **_k):
            return None

        text = ensure_description_zh(
            "baoyu-comic",
            description="Knowledge comic creator",
            category="content",
            force=True,
            use_llm=True,
            llm_fn=boom,
        )
        self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in text))
        self.assertGreater(len(text), 20)
    def test_install_hook_attaches_fields(self) -> None:
        from skill_description_zh import maybe_generate_on_install

        item = maybe_generate_on_install(
            {
                "name": "baoyu-translate",
                "description": "Translate articles",
                "category": "docs",
                "category_label": "文档处理",
                "display_name": "translate",
            }
        )
        self.assertTrue(item.get("description_zh"))
        self.assertEqual(item.get("description_display"), item.get("description_zh"))


if __name__ == "__main__":
    unittest.main()
