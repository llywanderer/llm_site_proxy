"""生图 Skill 预览图：约定路径、从 examples 物化、异步生成、列表字段。

规范文件：``{skill_dir}/preview.png``
状态：ready | pending | failed | missing | n/a
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("cursor_openai_bridge.skill_preview")

PREVIEW_FILENAME = "preview.png"
_PENDING_MARKER = ".preview_pending"
_FAILED_MARKER = ".preview_failed"
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# 仅认「样张」目录；不要扫 assets/outputs/根目录——会误把微信二维码、hero.gif、图标当画风
_EXAMPLE_DIRS = ("examples", "assets/examples")
_JUNK_NAME_PARTS = (
    "qrcode",
    "qr-code",
    "wechat-qr",
    "wechat_qr",
    "hero",
    "banner",
    "logo",
    "favicon",
    "icon",
    "avatar",
    "screenshot",
)

_DEFAULT_PROMPT = (
    "Create one showcase still image that clearly demonstrates this skill's visual style. "
    "Subject: a calm desk still-life with an open book, ceramic cup, and soft window light. "
    "No text, no watermark, no UI chrome, no QR code, no social-media promo banner. "
    "Square composition, polished final render."
)

_NAME_HINTS = (
    "illustration",
    "illustrations",
    "poster",
    "comic",
    "image-gen",
    "image_gen",
    "image-prompt",
    "cover-image",
    "xhs-image",
    "xhs-images",
    "infographic",
    "pixel",
    "hand-drawn",
    "oil-visual",
    "photo-",
    "photo-relic",
    "brandkit",
    "imagegen",
    "cartoon",
    "zine",
    "morandi",
    "gimi",
    "baoyu-image",
    "baoyu-comic",
    "baoyu-cover",
    "baoyu-xhs",
    "baoyu-infographic",
    "littlebox",
)

# 明确不是「画风/配图」：成片、思维人物、工程等，禁止进生图栏
_NON_IMAGE_CATEGORIES = frozenset(
    {
        "perspective",
        "motion",
        "engineering",
        "game",
        "publish",
        "docs",
        "utility",
        "platform",
    }
)
_IMAGE_CATEGORIES = frozenset({"content", "generation"})
_NON_IMAGE_NAME_PARTS = (
    "remotion",
    "-perspective",
    "perspective-",
)

_lock = threading.RLock()
_running: set[str] = set()
_queue: list[tuple[str, Path | None, bool]] = []
_queued_names: set[str] = set()
_worker_started = False
_worker_cv = threading.Condition(_lock)


def preview_enabled() -> bool:
    return os.environ.get("CURSOR_SKILLS_PREVIEW", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def preview_on_install_enabled() -> bool:
    if not preview_enabled():
        return False
    return os.environ.get("CURSOR_SKILLS_PREVIEW_ON_INSTALL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def preview_generate_enabled() -> bool:
    if not preview_enabled():
        return False
    return os.environ.get("CURSOR_SKILLS_PREVIEW_GENERATE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def default_preview_prompt() -> str:
    raw = (os.environ.get("CURSOR_SKILLS_PREVIEW_PROMPT") or "").strip()
    return raw or _DEFAULT_PROMPT


def preview_file(skill_dir: Path) -> Path:
    return skill_dir / PREVIEW_FILENAME


def is_image_style_skill(item: dict[str, Any] | None = None, *, name: str = "") -> bool:
    """是否为「画风/配图」类 skill（需要预览与进入生图选型）。

    硬排除：思维视角（*-perspective）、成片运动（remotion）、工程/游戏等非配图类目。
    正向：image 标签，或名称画风暗示且类目为 content/generation/other（或尚未归类）。
    """
    row = item or {}
    n = str(row.get("name") or name or "").strip().lower()
    if not n:
        return False

    # 1) 名称硬排除（人物视角 / Remotion 成片）
    if n == "booktok-remotion" or any(part in n for part in _NON_IMAGE_NAME_PARTS):
        return False

    cat = str(row.get("category") or "").strip().lower()
    if cat in _NON_IMAGE_CATEGORIES:
        return False

    purposes = row.get("purposes")
    if isinstance(purposes, list) and purposes:
        purpose_set = {str(p).strip().lower() for p in purposes if str(p).strip()}
        # 成片栏专用
        if purpose_set == {"motion"}:
            return False

    tag_ids = row.get("tag_ids")
    if isinstance(tag_ids, list) and any(str(t).lower() == "image" for t in tag_ids):
        return True
    tags = row.get("tags")
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict) and str(t.get("id") or "").lower() == "image":
                return True
            if str(t).lower() == "image":
                return True

    if any(h in n for h in _NAME_HINTS):
        if not cat or cat in _IMAGE_CATEGORIES or cat == "other":
            return True
        return False
    return False


def _is_usable_example_image(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in _IMAGE_EXTS:
        return False
    if name.startswith(".") or name == PREVIEW_FILENAME:
        return False
    if any(part in name for part in _JUNK_NAME_PARTS):
        return False
    # 营销动图不当作画风样张
    if path.suffix.lower() == ".gif":
        return False
    return True


def find_example_image(skill_dir: Path) -> Path | None:
    """在 examples / assets/examples，以及任意名为 examples 的子目录中找样张。"""
    searched: list[Path] = []
    for rel in _EXAMPLE_DIRS:
        root = skill_dir / rel
        if root.is_dir():
            searched.append(root)
    for examples_dir in sorted(skill_dir.rglob("examples")):
        if not examples_dir.is_dir():
            continue
        if any(part.startswith(".") for part in examples_dir.relative_to(skill_dir).parts):
            continue
        if examples_dir not in searched:
            searched.append(examples_dir)
    for root in searched:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if not _is_usable_example_image(path):
                continue
            return path
    return None


def materialize_from_examples(skill_dir: Path, *, force: bool = False) -> bool:
    dest = preview_file(skill_dir)
    if dest.is_file() and not force:
        return True
    src = find_example_image(skill_dir)
    if src is None:
        return False
    try:
        shutil.copy2(src, dest)
        _clear_markers(skill_dir)
        return True
    except OSError as e:
        log.warning("拷贝 preview 失败 skill=%s src=%s err=%s", skill_dir.name, src, e)
        return False


def _clear_markers(skill_dir: Path) -> None:
    for name in (_PENDING_MARKER, _FAILED_MARKER):
        p = skill_dir / name
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def _set_pending(skill_dir: Path) -> None:
    try:
        (skill_dir / _PENDING_MARKER).write_text(str(time.time()), encoding="utf-8")
        failed = skill_dir / _FAILED_MARKER
        if failed.exists():
            failed.unlink()
    except OSError:
        pass


def _set_failed(skill_dir: Path, error: str) -> None:
    try:
        (skill_dir / _FAILED_MARKER).write_text((error or "")[:2000], encoding="utf-8")
        pending = skill_dir / _PENDING_MARKER
        if pending.exists():
            pending.unlink()
    except OSError:
        pass


def preview_status_for_dir(skill_dir: Path, *, image_style: bool) -> str:
    if not image_style:
        return "n/a"
    if preview_file(skill_dir).is_file():
        return "ready"
    if (skill_dir / _PENDING_MARKER).is_file():
        return "pending"
    if (skill_dir / _FAILED_MARKER).is_file():
        return "failed"
    return "missing"


def preview_url_for(name: str) -> str:
    return f"/v1/skills/{name}/preview"


def attach_preview_fields(item: dict[str, Any], *, skill_dir: Path | None = None) -> dict[str, Any]:
    """就地写入 preview_* / is_image_style（含 meta 三态覆盖）。"""
    name = str(item.get("name") or "").strip()
    override: bool | None = None
    try:
        from skill_meta_store import get_is_image_style_override
    except ImportError:
        try:
            from .skill_meta_store import get_is_image_style_override  # type: ignore
        except ImportError:
            get_is_image_style_override = None  # type: ignore
    if get_is_image_style_override is not None and name:
        try:
            override = get_is_image_style_override(name)
        except Exception:  # noqa: BLE001
            override = None

    if isinstance(override, bool):
        image_style = override
        item["is_image_style"] = image_style
        item["is_image_style_source"] = "meta"
        item["is_image_style_override"] = override
    else:
        image_style = is_image_style_skill(item, name=name)
        item["is_image_style"] = image_style
        item["is_image_style_source"] = "auto"
        item["is_image_style_override"] = None

    if not preview_enabled() or not name:
        item["has_preview"] = False
        item["preview_status"] = "n/a" if not image_style else "missing"
        item["preview_url"] = None
        return item

    root = skill_dir
    if root is None:
        path_raw = str(item.get("path") or "").strip()
        root = Path(path_raw) if path_raw else None
    if root is None or not root.is_dir():
        item["has_preview"] = False
        item["preview_status"] = "n/a" if not image_style else "missing"
        item["preview_url"] = preview_url_for(name) if image_style else None
        return item

    status = preview_status_for_dir(root, image_style=image_style)
    item["preview_status"] = status
    item["has_preview"] = status == "ready"
    item["preview_url"] = preview_url_for(name) if image_style else None
    return item


def _build_agent_prompt(skill_name: str, out_png: Path, user_prompt: str) -> str:
    w, h = 1024, 1024
    return (
        f"【最高优先级 · Cursor 生图 Skills】必须优先遵循已安装 Skill `/{skill_name}` "
        f"（完整加载其 SKILL.md 工作流与风格约束）。\n\n"
        f"{user_prompt.strip()}\n\n"
        f"Write the final PNG to this exact path and nowhere else:\n{out_png}\n"
        f"Target size about {w}x{h}. Use the image generation tool if available. "
        f"When done, print DONE."
    )


def generate_preview_sync(
    name: str,
    *,
    root: Path | None = None,
    force: bool = False,
    run_agent: Callable[..., Any] | None = None,
    agent_timeout: float | None = None,
) -> dict[str, Any]:
    """同步生成/物化 preview.png。"""
    try:
        from skills_store import SkillStoreError, skills_root, validate_skill_name
    except ImportError:
        from .skills_store import SkillStoreError, skills_root, validate_skill_name  # type: ignore

    n = validate_skill_name(name)
    skill_dir = skills_root(root) / n
    if not skill_dir.is_dir():
        raise SkillStoreError(f"skill 不存在: {n}", status_code=404)

    item = {"name": n, "path": str(skill_dir)}
    try:
        from skill_taxonomy import enrich_skill_item
    except ImportError:
        from .skill_taxonomy import enrich_skill_item  # type: ignore
    enrich_skill_item(item)
    if not is_image_style_skill(item):
        attach_preview_fields(item, skill_dir=skill_dir)
        return {
            "name": n,
            "ok": True,
            "skipped": True,
            "reason": "not_image_style",
            **{k: item.get(k) for k in ("has_preview", "preview_status", "preview_url", "is_image_style")},
        }

    dest = preview_file(skill_dir)
    if dest.is_file() and not force:
        attach_preview_fields(item, skill_dir=skill_dir)
        return {
            "name": n,
            "ok": True,
            "skipped": True,
            "reason": "already_ready",
            **{k: item.get(k) for k in ("has_preview", "preview_status", "preview_url", "is_image_style")},
        }

    # force=True 时跳过物化，强制走 agent 重画（避免再次拷贝错误样张）
    if not force and materialize_from_examples(skill_dir, force=False):
        attach_preview_fields(item, skill_dir=skill_dir)
        return {
            "name": n,
            "ok": True,
            "source": "examples",
            **{k: item.get(k) for k in ("has_preview", "preview_status", "preview_url", "is_image_style")},
        }

    if force and dest.is_file():
        try:
            dest.unlink()
        except OSError:
            pass

    if not preview_generate_enabled():
        attach_preview_fields(item, skill_dir=skill_dir)
        return {
            "name": n,
            "ok": False,
            "error": "preview generate disabled and no examples",
            **{k: item.get(k) for k in ("has_preview", "preview_status", "preview_url", "is_image_style")},
        }

    agent_fn = run_agent
    if agent_fn is None:
        try:
            from .cursor_automation import run_cursor_agent as _rca
        except ImportError:
            from cursor_automation import run_cursor_agent as _rca  # type: ignore
        agent_fn = _rca

    try:
        timeout = float(
            agent_timeout
            if agent_timeout is not None
            else os.environ.get("CURSOR_SKILLS_PREVIEW_TIMEOUT", "600")
        )
    except ValueError:
        timeout = 600.0

    _set_pending(skill_dir)
    out_png = dest.resolve()
    prompt = _build_agent_prompt(n, out_png, default_preview_prompt())
    # workspace 用 skills 根目录，便于 agent 写到 skill 子目录
    try:
        from skills_store import skills_root as _sr
    except ImportError:
        from .skills_store import skills_root as _sr  # type: ignore
    workspace = _sr(root)

    try:
        r = agent_fn(
            prompt,
            workspace=workspace,
            output_format="json",
            trust=True,
            force=True,
            timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001
        _set_failed(skill_dir, str(e))
        raise

    if getattr(r, "returncode", 1) != 0:
        msg = (getattr(r, "stderr", None) or getattr(r, "stdout", None) or "agent 失败")
        msg = str(msg).strip()[:8000]
        _set_failed(skill_dir, msg)
        raise SkillStoreError(f"preview 生成失败: {msg}", status_code=502)

    if not dest.is_file():
        # 回退：取 skill 目录内最新产生的光栅图
        newest: Path | None = None
        newest_mtime = 0.0
        for path in skill_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
                continue
            if path.name.startswith("."):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= newest_mtime:
                newest_mtime = mtime
                newest = path
        if newest is not None and newest != dest:
            try:
                shutil.copy2(newest, dest)
            except OSError:
                newest = None
        if not dest.is_file():
            _set_failed(skill_dir, "agent 未写出 preview.png")
            raise SkillStoreError("preview 生成失败：未找到 PNG", status_code=502)

    _clear_markers(skill_dir)
    attach_preview_fields(item, skill_dir=skill_dir)
    return {
        "name": n,
        "ok": True,
        "source": "generated",
        **{k: item.get(k) for k in ("has_preview", "preview_status", "preview_url", "is_image_style")},
    }


def preview_auto_backfill_enabled() -> bool:
    if not preview_enabled():
        return False
    return os.environ.get("CURSOR_SKILLS_PREVIEW_AUTO_BACKFILL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _preview_queue_delay_sec() -> float:
    try:
        return max(0.0, float(os.environ.get("CURSOR_SKILLS_PREVIEW_QUEUE_DELAY", "2")))
    except ValueError:
        return 2.0


def _ensure_preview_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True

    def _worker() -> None:
        while True:
            with _worker_cv:
                while not _queue:
                    _worker_cv.wait(timeout=30.0)
                    if not _queue:
                        continue
                name, root, force = _queue.pop(0)
                _queued_names.discard(name)
                _running.add(name)
            try:
                try:
                    from skills_store import skills_root, validate_skill_name
                except ImportError:
                    from .skills_store import skills_root, validate_skill_name  # type: ignore
                skill_dir = skills_root(root) / validate_skill_name(name)
                if skill_dir.is_dir() and not preview_file(skill_dir).is_file():
                    _set_pending(skill_dir)
                result = generate_preview_sync(name, root=root, force=force)
                if result.get("has_preview") or result.get("ok"):
                    log.info(
                        "skill preview ready name=%s source=%s",
                        name,
                        result.get("source") or result.get("reason") or "ok",
                    )
                else:
                    log.warning(
                        "skill preview incomplete name=%s err=%s",
                        name,
                        result.get("error"),
                    )
            except Exception as e:  # noqa: BLE001
                log.warning("skill preview job failed name=%s err=%s", name, e)
            finally:
                with _lock:
                    _running.discard(name)
            delay = _preview_queue_delay_sec()
            if delay > 0:
                time.sleep(delay)

    threading.Thread(target=_worker, name="skill-preview-worker", daemon=True).start()
    log.info("skill preview background worker started")


def enqueue_preview(
    name: str,
    *,
    root: Path | None = None,
    force: bool = False,
) -> bool:
    """串行队列入队；同名去重。返回是否新入队。"""
    n = (name or "").strip()
    if not n or not preview_enabled():
        return False
    _ensure_preview_worker()
    with _worker_cv:
        if n in _queued_names or n in _running:
            return False
        if not force:
            try:
                from skills_store import skills_root, validate_skill_name
            except ImportError:
                from .skills_store import skills_root, validate_skill_name  # type: ignore
            dest = preview_file(skills_root(root) / validate_skill_name(n))
            if dest.is_file():
                return False
        _queue.append((n, root, force))
        _queued_names.add(n)
        _worker_cv.notify()
    return True


def schedule_preview_job(
    name: str,
    *,
    root: Path | None = None,
    force: bool = False,
) -> bool:
    """后台生成（串行队列，避免并发打爆 cursor agent）。"""
    return enqueue_preview(name, root=root, force=force)


def start_preview_autogen(*, delay_sec: float = 3.0) -> None:
    """进程启动后：先物化 examples，再把缺图的画风 skill 丢进后台队列。"""
    if not preview_auto_backfill_enabled():
        log.info("skill preview auto-backfill disabled")
        return
    _ensure_preview_worker()

    def _boot() -> None:
        if delay_sec > 0:
            time.sleep(delay_sec)
        try:
            from skills_store import list_skills, skills_root
        except ImportError:
            from .skills_store import list_skills, skills_root  # type: ignore
        try:
            skills = list_skills()
        except Exception as e:  # noqa: BLE001
            log.warning("preview autogen list_skills failed: %s", e)
            return
        queued = 0
        materialized = 0
        root = skills_root()
        for row in skills:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if not name or not is_image_style_skill(row):
                continue
            skill_dir = root / name
            if not skill_dir.is_dir():
                continue
            if preview_file(skill_dir).is_file():
                continue
            if materialize_from_examples(skill_dir):
                materialized += 1
                continue
            if enqueue_preview(name, force=False):
                queued += 1
        log.info(
            "skill preview autogen boot materialized=%s queued=%s",
            materialized,
            queued,
        )

    threading.Thread(target=_boot, name="skill-preview-autogen", daemon=True).start()


def ensure_preview(
    name: str,
    *,
    force: bool = False,
    root: Path | None = None,
    sync: bool = True,
) -> dict[str, Any]:
    """确保 preview：sync=True 阻塞生成；False 则后台调度。"""
    if sync:
        return generate_preview_sync(name, root=root, force=force)
    schedule_preview_job(name, root=root, force=force)
    try:
        from skills_store import get_skill
    except ImportError:
        from .skills_store import get_skill  # type: ignore
    item = get_skill(name, root=root) or {"name": name}
    return {
        "name": name,
        "ok": True,
        "queued": True,
        "preview_status": item.get("preview_status"),
        "has_preview": item.get("has_preview"),
        "preview_url": item.get("preview_url"),
        "is_image_style": item.get("is_image_style"),
    }


def maybe_preview_on_install(item: dict[str, Any]) -> dict[str, Any]:
    """安装成功后：物化 examples 或异步生成。"""
    attach_preview_fields(item)
    if not preview_on_install_enabled():
        return item
    name = str(item.get("name") or "").strip()
    if not name or not is_image_style_skill(item):
        return item
    path_raw = str(item.get("path") or "").strip()
    skill_dir = Path(path_raw) if path_raw else None
    if skill_dir and skill_dir.is_dir():
        if materialize_from_examples(skill_dir):
            attach_preview_fields(item, skill_dir=skill_dir)
            return item
    schedule_preview_job(name, force=False)
    if skill_dir and skill_dir.is_dir():
        _set_pending(skill_dir)
        attach_preview_fields(item, skill_dir=skill_dir)
    else:
        item["preview_status"] = "pending"
        item["has_preview"] = False
    return item


def backfill_previews(
    skills: list[dict[str, Any]],
    *,
    force: bool = False,
    sync: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    """批量补预览。默认异步排队。"""
    queued: list[str] = []
    ready: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []
    count = 0
    for row in skills:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name or not is_image_style_skill(row):
            if name:
                skipped.append(name)
            continue
        if limit > 0 and count >= limit:
            break
        count += 1
        try:
            if sync:
                result = generate_preview_sync(name, force=force)
                if result.get("has_preview") or result.get("ok"):
                    ready.append(name)
                else:
                    errors.append({"name": name, "error": str(result.get("error") or "failed")})
            else:
                path_raw = str(row.get("path") or "").strip()
                skill_dir = Path(path_raw) if path_raw else None
                if skill_dir and skill_dir.is_dir() and not force:
                    if materialize_from_examples(skill_dir):
                        ready.append(name)
                        continue
                    if preview_file(skill_dir).is_file():
                        ready.append(name)
                        continue
                if schedule_preview_job(name, force=force):
                    queued.append(name)
                else:
                    skipped.append(name)
        except Exception as e:  # noqa: BLE001
            errors.append({"name": name, "error": str(e)[:500]})
    return {
        "queued": queued,
        "ready": ready,
        "skipped": skipped,
        "errors": errors,
        "queued_count": len(queued),
        "ready_count": len(ready),
        "error_count": len(errors),
    }
