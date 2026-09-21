"""skill_preview 单元测试（不依赖 cursor agent）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skill_preview import (
    attach_preview_fields,
    find_example_image,
    is_image_style_skill,
    materialize_from_examples,
    preview_file,
)


class SkillPreviewTests(unittest.TestCase):
    def test_is_image_style_by_category(self):
        # content/generation  alone 不再自动算画风
        self.assertFalse(is_image_style_skill({"name": "foo", "category": "content"}))
        self.assertFalse(is_image_style_skill({"name": "foo", "category": "docs"}))
        self.assertTrue(
            is_image_style_skill({"name": "foo", "category": "content", "tag_ids": ["image"]})
        )

    def test_is_image_style_by_name_hint(self):
        self.assertTrue(is_image_style_skill({"name": "gimi-illustration", "category": "other"}))
        self.assertTrue(is_image_style_skill(name="pixel-style-poster-skill"))

    def test_excludes_perspective_and_remotion(self):
        self.assertFalse(
            is_image_style_skill(
                {
                    "name": "paul-graham-perspective",
                    "category": "perspective",
                    "purposes": ["text"],
                    "tag_ids": ["image"],
                }
            )
        )
        self.assertFalse(
            is_image_style_skill(
                {
                    "name": "remotion-best-practices",
                    "category": "motion",
                    "purposes": ["motion"],
                }
            )
        )
        self.assertFalse(
            is_image_style_skill({"name": "remotion-create", "category": "content"})
        )
        self.assertFalse(
            is_image_style_skill(
                {"name": "naval-perspective", "category": "content", "purposes": ["image"]}
            )
        )

    def test_meta_override_beats_auto_and_hard_exclude(self):
        import os
        import tempfile

        from skill_meta_store import set_is_image_style_override

        with tempfile.TemporaryDirectory() as td:
            skills = Path(td) / "skills"
            skills.mkdir()
            os.environ["CURSOR_SKILLS_DIR"] = str(skills)
            os.environ.pop("CURSOR_SKILLS_META_PATH", None)

            # auto: handdraw 无 hint → false
            item = {"name": "handdraw-style-prompter", "category": "content"}
            attach_preview_fields(item)
            self.assertFalse(item["is_image_style"])
            self.assertEqual(item["is_image_style_source"], "auto")
            self.assertIsNone(item["is_image_style_override"])

            set_is_image_style_override("handdraw-style-prompter", True)
            attach_preview_fields(item)
            self.assertTrue(item["is_image_style"])
            self.assertEqual(item["is_image_style_source"], "meta")
            self.assertTrue(item["is_image_style_override"])

            # meta true 压过 perspective 硬排除
            set_is_image_style_override("naval-perspective", True)
            pers = {
                "name": "naval-perspective",
                "category": "perspective",
                "purposes": ["text"],
            }
            attach_preview_fields(pers)
            self.assertTrue(pers["is_image_style"])
            self.assertEqual(pers["is_image_style_source"], "meta")

            # meta false 压过名称 hint
            set_is_image_style_override("gimi-illustration", False)
            gimi = {"name": "gimi-illustration", "category": "other"}
            attach_preview_fields(gimi)
            self.assertFalse(gimi["is_image_style"])
            self.assertEqual(gimi["is_image_style_source"], "meta")

    def test_materialize_from_examples(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = root / "hand-drawn"
            examples = skill / "examples"
            examples.mkdir(parents=True)
            src = examples / "a.png"
            src.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            self.assertTrue(materialize_from_examples(skill))
            dest = preview_file(skill)
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_bytes(), src.read_bytes())
            item = {"name": "hand-drawn", "category": "content", "path": str(skill)}
            attach_preview_fields(item, skill_dir=skill)
            self.assertTrue(item["has_preview"])
            self.assertEqual(item["preview_status"], "ready")
            self.assertEqual(item["preview_url"], "/v1/skills/hand-drawn/preview")

    def test_find_example_prefers_examples_dir(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "x"
            (skill / "outputs").mkdir(parents=True)
            (skill / "examples").mkdir(parents=True)
            out = skill / "outputs" / "late.png"
            out.write_bytes(b"out")
            ex = skill / "examples" / "early.png"
            ex.write_bytes(b"ex")
            found = find_example_image(skill)
            self.assertEqual(found, ex)

    def test_ignores_root_wechat_qrcode_and_assets(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "mrbeast-perspective"
            skill.mkdir()
            (skill / "wechat-qrcode.jpg").write_bytes(b"qr")
            (skill / "assets").mkdir()
            (skill / "assets" / "hero.gif").write_bytes(b"gif")
            self.assertIsNone(find_example_image(skill))
            self.assertFalse(is_image_style_skill({"name": "mrbeast-perspective", "path": str(skill)}))

    def test_ignores_junk_named_example(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "gimi-illustration"
            examples = skill / "examples"
            examples.mkdir(parents=True)
            (examples / "wechat-qrcode.jpg").write_bytes(b"qr")
            (examples / "style-demo.png").write_bytes(b"ok")
            found = find_example_image(skill)
            self.assertEqual(found.name, "style-demo.png")


if __name__ == "__main__":
    unittest.main()
