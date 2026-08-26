"""安装/回填时用 LLM 根据 skill 介绍推断分类，写入 ``inferred_by_name``。"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

log = logging.getLogger("cursor_openai_bridge.skill_category_llm")

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_WHITESPACE_RE = re.compile(r"\s+")


def _env_flag(name: str, default: str = "1") -> bool:
    raw = (os.environ.get(name) if os.environ.get(name) is not None else default) or default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def category_llm_enabled() -> bool:
    return _env_flag("CURSOR_SKILLS_CATEGORY_LLM", "1")


def category_on_install_enabled() -> bool:
    return _env_flag("CURSOR_SKILLS_CATEGORY_ON_INSTALL", "1")


def _llm_timeout() -> float:
    try:
        return max(5.0, float(os.environ.get("CURSOR_SKILLS_ZH_TIMEOUT") or "60"))
    except ValueError:
        return 60.0


def _default_llm_url() -> str:
    override = (os.environ.get("CURSOR_SKILLS_ZH_LLM_URL") or "").strip()
    if override:
        return override
    port = (os.environ.get("CURSOR_BRIDGE_PORT") or "8765").strip() or "8765"
    return f"http://127.0.0.1:{port}/v1/chat/completions"


def _llm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = (
        (os.environ.get("CURSOR_SKILLS_ZH_LLM_API_KEY") or "").strip()
        or (os.environ.get("CURSOR_OPENAI_BRIDGE_API_KEY") or "").strip()
    )
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _compact(text: str, max_len: int = 800) -> str:
    s = _WHITESPACE_RE.sub(" ", (text or "").strip())
    if len(s) <= max_len:
        return s
    return s[: max(1, max_len - 1)].rstrip() + "…"


def _category_catalog_text(categories: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for c in categories:
        cid = str(c.get("id") or "").strip()
        if not cid or cid == "other":
            continue
        label = str(c.get("label") or cid)
        hint = str(c.get("hint") or "")
        lines.append(f"- {cid}: {label} — {hint}")
    return "\n".join(lines)


def _parse_category_id(raw: str, *, known: set[str]) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:\w+)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    candidates: list[str] = []
    # 显式 "category: content" / "id=docs"
    for m in re.finditer(
        r"(?:category|id|分类)\s*[:=：]\s*([a-z][a-z0-9_-]{0,63})",
        text,
        flags=re.I,
    ):
        candidates.append(m.group(1).lower())

    # 整行几乎只有一个 id
    for line in text.splitlines():
        token = line.strip().strip("`\"'").lower()
        if _ID_RE.fullmatch(token):
            candidates.append(token)

    # 全文搜已知 id（按出现顺序）
    lowered = text.lower()
    for cid in sorted(known, key=len, reverse=True):
        if not cid or cid == "other":
            continue
        if re.search(rf"(?<![a-z0-9_-]){re.escape(cid)}(?![a-z0-9_-])", lowered):
            candidates.append(cid)

    for cid in reversed(candidates):
        if cid in known and cid != "other":
            return cid
    if "other" in candidates and "other" in known:
        return None
    return None


def classify_category_llm(
    name: str,
    *,
    description: str = "",
    description_zh: str = "",
    categories: list[dict[str, Any]] | None = None,
    timeout: float | None = None,
) -> str | None:
    """调用 LLM 返回规范 category id；失败返回 None。"""
    try:
        from skill_taxonomy import list_categories
    except ImportError:
        from .skill_taxonomy import list_categories  # type: ignore

    cats = categories if categories is not None else list_categories()
    known = {str(c.get("id") or "") for c in cats}
    catalog = _category_catalog_text(cats)
    if not catalog:
        return None

    url = _default_llm_url()
    model = (os.environ.get("CURSOR_SKILLS_ZH_LLM_MODEL") or "auto").strip() or "auto"
    wait = _llm_timeout() if timeout is None else max(5.0, float(timeout))
    desc = _compact(description_zh or description, 900)
    if not desc:
        desc = "(无介绍)"

    system = (
        "你是 Skills 分类助手。根据 skill 名称与介绍，从给定分类 id 中选且仅选一个最贴切的。"
        "硬性要求：回复全文只能是一个分类 id（小写英文），禁止解释、禁止标点、禁止换行、禁止其它文字。"
        "若实在无法判断，只输出 other。"
    )
    user = (
        f"可选分类 id（只能选其中一个）:\n{catalog}\n\n"
        f"skill 名称: {name}\n"
        f"介绍:\n{desc}\n\n"
        "现在只输出一个分类 id："
    )
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 32,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=_llm_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=wait) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as e:
        log.warning("skill category LLM 失败 name=%s err=%s", name, e)
        return None

    text = ""
    try:
        choices = payload.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            text = str(msg.get("content") or "").strip()
    except (AttributeError, IndexError, TypeError):
        text = ""
    hit = _parse_category_id(text, known=known)
    if not hit:
        log.warning("skill category LLM 输出无效 name=%s raw=%r", name, text[:80])
        return None
    return hit


def classify_categories_batch_llm(
    items: list[dict[str, str]],
    *,
    categories: list[dict[str, Any]] | None = None,
    timeout: float | None = None,
) -> dict[str, str]:
    """一次请求为多个 skill 分类；返回 name→category_id（仅有效项）。"""
    try:
        from skill_taxonomy import list_categories
    except ImportError:
        from .skill_taxonomy import list_categories  # type: ignore

    if not items:
        return {}
    cats = categories if categories is not None else list_categories()
    known = {str(c.get("id") or "") for c in cats}
    catalog = _category_catalog_text(cats)
    if not catalog:
        return {}

    lines: list[str] = []
    names: list[str] = []
    for row in items:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        names.append(name)
        desc = _compact(
            str(row.get("description_zh") or row.get("description") or ""),
            280,
        )
        lines.append(f"- {name}: {desc or '(无介绍)'}")
    if not lines:
        return {}

    url = _default_llm_url()
    model = (os.environ.get("CURSOR_SKILLS_ZH_LLM_MODEL") or "auto").strip() or "auto"
    # 批量稍放宽超时
    base = _llm_timeout() if timeout is None else max(5.0, float(timeout))
    wait = max(base, min(300.0, base + 15.0 * len(lines)))
    system = (
        "你是 Skills 分类助手。为每个 skill 从给定分类 id 中选一个最贴切的。"
        "只输出 JSON 对象：键为 skill 名称，值为分类 id（小写）。"
        "不要 markdown 代码围栏，不要解释。无法判断的值用 other。"
    )
    user = (
        f"可选分类 id:\n{catalog}\n\n"
        f"待分类 skills:\n" + "\n".join(lines) + "\n\n"
        "输出 JSON:"
    )
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": min(4000, 40 * len(lines) + 200),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=_llm_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=wait) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as e:
        log.warning("skill category batch LLM 失败 n=%s err=%s", len(lines), e)
        return {}

    text = ""
    try:
        choices = payload.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            text = str(msg.get("content") or "").strip()
    except (AttributeError, IndexError, TypeError):
        text = ""
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    # 截取第一个 {...}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        log.warning("skill category batch 无 JSON n=%s raw=%r", len(lines), text[:120])
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        log.warning("skill category batch JSON 无效 n=%s", len(lines))
        return {}
    if not isinstance(data, dict):
        return {}

    out: dict[str, str] = {}
    name_set = set(names)
    for k, v in data.items():
        name = str(k).strip()
        if name not in name_set:
            continue
        cid = _parse_category_id(str(v), known=known)
        if cid:
            out[name] = cid
    return out


def ensure_inferred_category(
    name: str,
    *,
    description: str = "",
    description_zh: str = "",
    frontmatter: dict[str, Any] | None = None,
    force: bool = False,
    use_llm: bool | None = None,
    llm_fn: Callable[..., str | None] | None = None,
) -> str | None:
    """必要时 LLM 推断并持久化；返回最终推断 id（或已有推断）。"""
    try:
        from skill_meta_store import get_inferred_category, set_inferred_category
        from skill_taxonomy import needs_inferred_category
    except ImportError:
        from .skill_meta_store import get_inferred_category, set_inferred_category  # type: ignore
        from .skill_taxonomy import needs_inferred_category  # type: ignore

    n = (name or "").strip()
    if not n:
        return None

    existing = get_inferred_category(n)
    if existing and not force:
        if not needs_inferred_category(n, frontmatter=frontmatter):
            # 规则已能分类：不必再推断
            return existing
        return existing

    if not needs_inferred_category(n, frontmatter=frontmatter):
        return None

    do_llm = category_llm_enabled() if use_llm is None else bool(use_llm)
    if not do_llm:
        return existing

    classify = llm_fn or classify_category_llm
    try:
        hit = classify(
            n,
            description=description,
            description_zh=description_zh,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("skill category classify 异常 name=%s err=%s", n, e)
        hit = None
    if not hit or hit == "other":
        return existing
    set_inferred_category(n, hit)
    return hit


def maybe_categorize_on_install(item: dict[str, Any]) -> dict[str, Any]:
    """安装成功后可选 LLM 分类，并刷新 item 上的分类字段。"""
    if not category_on_install_enabled():
        return item
    name = str(item.get("name") or "").strip()
    if not name:
        return item
    try:
        ensure_inferred_category(
            name,
            description=str(item.get("description") or ""),
            description_zh=str(item.get("description_zh") or ""),
            force=False,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("install 后推断分类失败 name=%s err=%s", name, e)

    try:
        from skill_taxonomy import categorize_skill
    except ImportError:
        from .skill_taxonomy import categorize_skill  # type: ignore
    tax = categorize_skill(name)
    item.update(tax)
    return item


def backfill_categories(
    skills: list[dict[str, Any]],
    *,
    force: bool = False,
    use_llm: bool | None = None,
    batch_size: int = 12,
    llm_fn: Callable[..., str | None] | None = None,
    batch_llm_fn: Callable[..., dict[str, str]] | None = None,
) -> dict[str, Any]:
    """批量推断分类；优先按批调用 LLM，返回汇总。"""
    try:
        from skill_meta_store import get_inferred_category, set_inferred_category
        from skill_taxonomy import needs_inferred_category
    except ImportError:
        from .skill_meta_store import get_inferred_category, set_inferred_category  # type: ignore
        from .skill_taxonomy import needs_inferred_category  # type: ignore

    updated: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    do_llm = category_llm_enabled() if use_llm is None else bool(use_llm)
    pending: list[dict[str, str]] = []

    for row in skills:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            before = get_inferred_category(name)
            if before and not force:
                skipped.append(name)
                continue
            if not needs_inferred_category(name):
                skipped.append(name)
                continue
            if not do_llm:
                skipped.append(name)
                continue
            if llm_fn is not None:
                hit = ensure_inferred_category(
                    name,
                    description=str(row.get("description") or ""),
                    description_zh=str(row.get("description_zh") or ""),
                    force=force,
                    use_llm=True,
                    llm_fn=llm_fn,
                )
                if hit and hit != before:
                    updated.append(name)
                else:
                    skipped.append(name)
                continue
            pending.append(
                {
                    "name": name,
                    "description": str(row.get("description") or ""),
                    "description_zh": str(row.get("description_zh") or ""),
                }
            )
        except Exception as e:  # noqa: BLE001
            log.warning("backfill category 预处理失败 name=%s err=%s", name, e)
            failed.append(name)

    batch_fn = batch_llm_fn or classify_categories_batch_llm
    size = max(1, int(batch_size or 12))
    for i in range(0, len(pending), size):
        chunk = pending[i : i + size]
        try:
            mapping = batch_fn(chunk)
        except Exception as e:  # noqa: BLE001
            log.warning("backfill category 批次失败 n=%s err=%s", len(chunk), e)
            mapping = {}
        if not mapping:
            # 整批失败：逐条重试
            for row in chunk:
                name = row["name"]
                before = get_inferred_category(name)
                try:
                    hit = ensure_inferred_category(
                        name,
                        description=row.get("description") or "",
                        description_zh=row.get("description_zh") or "",
                        force=force,
                        use_llm=True,
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("backfill category 单条失败 name=%s err=%s", name, e)
                    failed.append(name)
                    continue
                if hit and hit != before:
                    updated.append(name)
                else:
                    skipped.append(name)
            continue
        for row in chunk:
            name = row["name"]
            before = get_inferred_category(name)
            hit = mapping.get(name)
            if not hit:
                # 批次已判定为 other/无效：保持 other，不再单条打 LLM
                skipped.append(name)
                continue
            try:
                set_inferred_category(name, hit)
            except Exception as e:  # noqa: BLE001
                log.warning("写入 inferred 失败 name=%s err=%s", name, e)
                failed.append(name)
                continue
            after = get_inferred_category(name)
            if after and after != before:
                updated.append(name)
            else:
                skipped.append(name)

    return {
        "ok": not failed,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
    }
