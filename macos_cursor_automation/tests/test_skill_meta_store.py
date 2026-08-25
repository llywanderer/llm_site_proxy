"""skill_meta_store 单元测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class SkillMetaStoreTests(unittest.TestCase):
    def test_tag_crud_and_skill_assign(self) -> None:
        from skill_meta_store import (
            SkillMetaError,
            create_tag,
            delete_tag,
            list_tags,
            resolve_skill_tags,
            set_skill_tags,
            update_tag,
        )

        with tempfile.TemporaryDirectory() as td:
            skills = Path(td) / "skills"
            skills.mkdir()
            os.environ["CURSOR_SKILLS_DIR"] = str(skills)
            os.environ.pop("CURSOR_SKILLS_META_PATH", None)

            # 默认种子标签
            seeded = {t["id"] for t in list_tags()}
            self.assertIn("text", seeded)

            create_tag(tag_id="wechat-ops", label="微信运营", color="#07c160")
            ids = {t["id"] for t in list_tags()}
            self.assertIn("wechat-ops", ids)

            with self.assertRaises(SkillMetaError):
                create_tag(tag_id="wechat-ops")

            update_tag("wechat-ops", label="微信")
            row = next(t for t in list_tags() if t["id"] == "wechat-ops")
            self.assertEqual(row["label"], "微信")

            tags = set_skill_tags("baoyu-cover-image", ["wechat-ops", "image"])
            self.assertEqual([t["id"] for t in tags], ["wechat-ops", "image"])
            self.assertEqual(
                [t["id"] for t in resolve_skill_tags("baoyu-cover-image")],
                ["wechat-ops", "image"],
            )

            delete_tag("wechat-ops")
            self.assertNotIn("wechat-ops", {t["id"] for t in list_tags()})
            self.assertEqual(
                [t["id"] for t in resolve_skill_tags("baoyu-cover-image")],
                ["image"],
            )

            meta_file = skills / ".skills-meta.json"
            self.assertTrue(meta_file.is_file())

    def test_description_zh_roundtrip(self) -> None:
        from skill_meta_store import (
            clear_description_zh,
            get_description_zh,
            patch_skill_meta,
            set_description_zh,
        )

        with tempfile.TemporaryDirectory() as td:
            skills = Path(td) / "skills"
            skills.mkdir()
            os.environ["CURSOR_SKILLS_DIR"] = str(skills)
            os.environ.pop("CURSOR_SKILLS_META_PATH", None)

            set_description_zh("remotion-markup", "Remotion 镜头与特效标记最佳实践。")
            self.assertIn("镜头", get_description_zh("remotion-markup") or "")
            patch_skill_meta("remotion-markup", description_zh="更新后的中文描述。")
            self.assertEqual(get_description_zh("remotion-markup"), "更新后的中文描述。")
            clear_description_zh("remotion-markup")
            self.assertIsNone(get_description_zh("remotion-markup"))


if __name__ == "__main__":
    unittest.main()
