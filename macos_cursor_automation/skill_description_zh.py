"""为 Skills 生成控制台用中文描述（不改 SKILL.md）。

流程：模板草稿 →（可选）LLM 润色 → 写入 ``.skills-meta.json`` 的 ``descriptions_zh``。
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

log = logging.getLogger("cursor_openai_bridge.skill_zh")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WHITESPACE_RE = re.compile(r"\s+")

# 已知 skill 的定制中文（优先于通用模板，仍可被 LLM 润色）
_KNOWN_CUSTOM: dict[str, str] = {
    "remotion-best-practices": (
        "Remotion 成片技能总路由：当任务涉及 Remotion 视频结构、镜头、转场、字幕或导出时，"
        "先经本技能分派到对应的 remotion-* 子技能。适用于 BookTok/工厂成片链路中勾选 Remotion 相关能力的场景；"
        "不负责另起新 Remotion 工程脚手架。"
    ),
    "remotion-create": (
        "工厂安全版 Remotion 创建：始终复用现有 BookTok Remotion 项目，禁止执行 npx create-video 或新建独立应用。"
        "在已有项目内增改 Composition/组件时使用；不要用它初始化全新仓库。"
    ),
    "remotion-captions": (
        "Remotion 字幕：转录、展示与动画字幕时间轴。成片需要字幕轨、字幕样式或口播对齐时使用；"
        "不替代 TTS 或整片渲染管线。"
    ),
    "remotion-render": (
        "Remotion 导出成片：把 Composition 渲染为视频文件。准备好时间轴与资源后导出时使用；"
        "不负责剧本或分镜创作。"
    ),
    "remotion-studio": "在 Remotion Studio 中预览时间轴与 Composition，调试镜头与时长时使用。",
    "remotion-docs": "检索 Remotion 官方文档与 API 用法，回答框架能力与配置问题时使用。",
    "remotion-markup": "Remotion 内容、动画与特效的标记与最佳实践，编写镜头结构与动效时使用。",
    "remotion-maps": "Remotion 地图动画知识：地理轨迹、缩放与标注类镜头时使用。",
    "remotion-interactivity": "为 Remotion 标记结构加入交互能力（点击、状态）时使用。",
    "remotion-multimedia": "在 Remotion 中对接 Mediabunny 等多媒体资源时使用。",
    "remotion-saas": "基于 Remotion 搭建可部署的应用/SaaS 形态成片服务时使用。",
    "remotion-upgrade": "升级 Remotion 及相关依赖包，处理破坏性变更时使用。",
    "booktok-remotion": (
        "BookTok Remotion 成片 Skill：镜头节奏与构图须与生文/生图 Skill、主体资产、片头片尾同时生效；"
        "禁止另起 Remotion 项目。工厂勾选成片能力时使用。"
    ),
    "agent-reach": (
        "互联网多平台调研路由器：覆盖搜索、社媒、招聘、视频、财经等渠道的只读采集。"
        "用户要调研/搜索/查资料，或提到小红书、X、B站、Reddit、LinkedIn、YouTube 等平台时必须使用；"
        "不负责写报告或发帖点赞等写操作。"
    ),
    "gimi-illustration": (
        "多风格文章配图 Skill：支持怪诞手绘、暖调绘本、产品方案等，以及自定义 IP 录入。"
        "为中文文案/BookTok 分镜生成插画，或登记角色形象时使用；须遵守 Skill 内 STYLE_DNA 与默认 quirky-sketch。"
    ),
    "guizang-social-card-skill": (
        "归藏风格社媒卡片：生成多页视觉卡片、Live Photo 动效与拼图布局。"
        "做小红书/社交封面组图或动效卡片时使用；按平台规格与 QA 清单出图。"
    ),
    "darwin-skill": (
        "达尔文 Skill 优化器：结合 SkillLens 等方法自动评估并改进 Agent Skill。"
        "需要诊断、改写或强化现有 Skill 时使用，而非日常业务内容生产。"
    ),
    "huashu-nuwa": (
        "女娲造人：按人名/主题深度调研并蒸馏出可运行的人物思维 Skill。"
        "用户说「造 skill」「蒸馏 XX」「女娲」时使用；输出为完整 perspective 类 Skill。"
    ),
    "x-mastery-mentor": (
        "X/Twitter 运营导师：标题、钩子、节奏与增长方法论。"
        "做推文策略、账号增长或内容公式拆解时使用。"
    ),
    "ip-diagram-creator": (
        "IP/信息图示意生成：把概念整理为清晰图示或结构图。"
        "需要示意图、架构表达或信息图草稿时使用。"
    ),
    "baoyu-article-illustrator": (
        "文章配图助手：分析文稿结构，在需要视觉辅助的位置生成插图（类型×风格×色板）。"
        "写长文/公众号需要配图时使用。"
    ),
    "baoyu-comic": (
        "知识漫画生成：多画风、多语气的科普/讲解漫画分镜与成图。"
        "要把知识点画成连环画时使用。"
    ),
    "baoyu-compress-image": (
        "图片压缩：默认转 WebP（可 PNG），自动选择压缩工具。"
        "需要缩小体积或统一格式时使用。"
    ),
    "baoyu-cover-image": (
        "文章封面图：按类型/色板/渲染/文字/情绪等维度组合生成封面。"
        "需要公众号或博客头图时使用。"
    ),
    "baoyu-danger-gemini-web": (
        "实验性 Gemini Web 通道：经逆向接口做文案或生图（有账号/合规风险）。"
        "仅在明确接受风险且需要该通道时使用。"
    ),
    "baoyu-danger-x-to-markdown": (
        "实验性 X/Twitter 转 Markdown：拉取推文或长文并带 YAML 头（依赖用户凭证，有风险）。"
        "需要把推文归档为 Markdown 时使用。"
    ),
    "baoyu-diagram": (
        "深色主题专业 SVG 图示：架构图、流程图、时序图、结构图等。"
        "需要可编辑矢量示意图时使用。"
    ),
    "baoyu-electron-extract": (
        "从已安装 Electron 应用的 asar 包提取资源与 JS 源码。"
        "需要逆向/审计 Electron 客户端静态资源时使用。"
    ),
    "baoyu-format-markdown": (
        "Markdown 排版：补 frontmatter、标题、摘要、列表与代码块格式。"
        "整理杂乱文稿为规范 Markdown 时使用。"
    ),
    "baoyu-image-gen": (
        "多通道 AI 生图：对接 OpenAI/Azure/Google/OpenRouter/通义/智谱/MiniMax 等。"
        "需要按统一 Skill 流程出图时使用。"
    ),
    "baoyu-infographic": (
        "信息图生成：多布局×多视觉风格，先分析内容再推荐版式。"
        "要把要点做成一页信息图时使用。"
    ),
    "baoyu-markdown-to-html": (
        "Markdown 转公众号友好 HTML：主题、代码高亮、公式与 Mermaid。"
        "准备微信图文 HTML 时使用。"
    ),
    "baoyu-post-to-wechat": (
        "发布到微信公众号：文章/草稿，支持 API 或 Chrome CDP。"
        "需要把成品推到公众号时使用。"
    ),
    "baoyu-post-to-weibo": (
        "发布到微博：普通博文与头条文章，支持图文视频。"
        "需要同步内容到微博时使用。"
    ),
    "baoyu-post-to-x": (
        "发布到 X/Twitter：普通推文与 X Articles。"
        "需要发推或发长文到 X 时使用。"
    ),
    "baoyu-slide-deck": (
        "幻灯片成图：先出大纲与风格说明，再逐页生成幻灯片图像。"
        "需要演示文稿视觉页而非 PPTX 工程时使用。"
    ),
    "baoyu-translate": (
        "文章精翻：中英等互译，保留结构与术语一致性。"
        "用户说翻译/精翻/translate article 时使用。"
    ),
    "baoyu-url-to-markdown": (
        "URL 转 Markdown：经 baoyu-fetch（Chrome CDP）抓取并转换。"
        "要把网页正文落成 Markdown 时使用。"
    ),
    "baoyu-wechat-summary": (
        "微信群聊精华摘要：基于本地 wx-cli 整理结构化日/周报。"
        "需要汇总群消息要点时使用。"
    ),
    "baoyu-xhs-images": (
        "小红书信息图卡片组：多风格/布局/色板，拆成 1–10 张竖版图。"
        "做小红书图文笔记配图时使用。"
    ),
    "baoyu-youtube-transcript": (
        "YouTube 字幕/封面拉取：按链接或视频 ID 下载多语言转写。"
        "需要视频文稿或封面素材时使用。"
    ),
}


def _env_flag(name: str, default: str = "1") -> bool:
    raw = (os.environ.get(name) or default).strip().lower()
    return raw not in ("0", "false", "no", "off", "")


def zh_llm_enabled() -> bool:
    return _env_flag("CURSOR_SKILLS_ZH_LLM", "1")


def zh_on_install_enabled() -> bool:
    return _env_flag("CURSOR_SKILLS_ZH_ON_INSTALL", "1")


def zh_llm_timeout() -> float:
    try:
        return max(5.0, float(os.environ.get("CURSOR_SKILLS_ZH_TIMEOUT") or "60"))
    except ValueError:
        return 60.0


def cjk_ratio(text: str) -> float:
    s = (text or "").strip()
    if not s:
        return 0.0
    return sum(1 for c in s if _CJK_RE.match(c)) / len(s)


def looks_chinese(text: str, *, min_chars: int = 24, min_ratio: float = 0.25) -> bool:
    s = (text or "").strip()
    if len(s) < min_chars:
        return False
    return cjk_ratio(s) >= min_ratio


def _compact(text: str, max_len: int = 480) -> str:
    s = _WHITESPACE_RE.sub(" ", (text or "").strip())
    if len(s) <= max_len:
        return s
    return s[: max(1, max_len - 1)].rstrip() + "…"


def _category_hint(category: str | None, category_label: str | None) -> str:
    label = (category_label or "").strip()
    if label:
        return label
    cid = (category or "").strip()
    mapping = {
        "perspective": "思维视角",
        "content": "内容创作",
        "publish": "发布分发",
        "docs": "文档处理",
        "generation": "生成后端",
        "utility": "工具箱",
        "platform": "平台/运维",
        "motion": "成片运动",
        "other": "通用能力",
    }
    return mapping.get(cid, "通用能力")


def draft_description_zh(
    name: str,
    *,
    description: str = "",
    category: str | None = None,
    category_label: str | None = None,
    display_name: str | None = None,
) -> str:
    """确定性中文草稿（永远有结果；不以大段英文充数）。"""
    n = (name or "").strip()
    if n in _KNOWN_CUSTOM:
        return _KNOWN_CUSTOM[n]

    src = (description or "").strip()
    # 仅当原文本身已是可读中文说明时直接采用（触发词堆叠的双语 description 不算）
    if looks_chinese(src, min_chars=28, min_ratio=0.35):
        return _compact(src, 520)

    cat = _category_hint(category, category_label)
    title = (display_name or n).strip() or n
    tip = _english_tip(src)

    if n.startswith("baoyu-"):
        return _compact(
            f"「{title}」是宝玉系列「{cat}」Skill，"
            f"在 Cursor Agent 中按该 Skill 的 CLI/样式约定完成专项自动化。"
            f"对话选用 /{n} 或任务明确需要该工具时使用；"
            f"勿与其它 baoyu-* 能力混用，参数与限制以 SKILL.md 为准。"
            ,
            560,
        )
    if n.endswith("-perspective"):
        who = title if title != n else n.replace("-perspective", "")
        return _compact(
            f"「{who}」思维视角 Skill：用该人物/专家的心智模型与表达方式分析问题、写稿或做决策。"
            f"提到「用{who}视角」或 /{n} 时使用；输出应贴合其表达 DNA，而非泛泛总结。"
            ,
            560,
        )
    if n.startswith("remotion-") or n == "booktok-remotion":
        return _compact(
            f"「{title}」属于成片运动（Remotion）能力。"
            f"工厂/成片链路需要镜头、字幕、渲染或项目约定时使用。"
            f"勿另起无关 Remotion 工程；优先走 booktok-remotion / remotion-best-practices 路由。"
            ,
            560,
        )

    tip_zh = tip if tip and cjk_ratio(tip) >= 0.3 else ""
    return _compact(
        f"「{title}」是「{cat}」类 Cursor Agent Skill，"
        f"用于指导模型按固定流程完成专项任务"
        f"{('。' + tip_zh) if tip_zh else ''}。"
        f"在控制台启用或对话中使用 /{n} 时触发；"
        f"不适用相邻领域的其它 Skill 职责，细节以 SKILL.md 正文为准。"
        ,
        560,
    )


def _english_tip(description: str, max_len: int = 96) -> str:
    """从英文 description 抽一句极短要点，避免整段英文污染中文展示。"""
    s = _WHITESPACE_RE.sub(" ", (description or "").strip())
    if not s:
        return ""
    # 若已有较多中文，取首句中文片段
    if cjk_ratio(s) >= 0.25:
        for part in re.split(r"[。！？\n]", s):
            part = part.strip()
            if part and cjk_ratio(part) >= 0.3:
                return _compact(part, max_len)
    # 英文：取第一句并截断
    first = re.split(r"(?<=[.!?])\s+", s, maxsplit=1)[0].strip()
    first = re.sub(r"^MUST USE when user wants to\s+", "", first, flags=re.I)
    return _compact(first, max_len)


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


def polish_description_zh_llm(
    name: str,
    draft: str,
    *,
    description: str = "",
    timeout: float | None = None,
) -> str | None:
    """调用 OpenAI 兼容接口润色；失败返回 None。"""
    url = _default_llm_url()
    model = (os.environ.get("CURSOR_SKILLS_ZH_LLM_MODEL") or "auto").strip() or "auto"
    wait = zh_llm_timeout() if timeout is None else max(5.0, float(timeout))
    system = (
        "你是 Skills 控制台文案助手。根据给定英文/草稿，输出一段详细的简体中文描述："
        "说明做什么、何时用、不适用什么。2～4 句，不要标题，不要引号包裹全文，不要复述 skill 文件夹名以外的英文命令。"
    )
    user = (
        f"skill 名称: {name}\n"
        f"原始 description:\n{description or '(空)'}\n\n"
        f"中文草稿:\n{draft}\n\n"
        "请输出润色后的中文描述："
    )
    body = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 400,
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
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as e:
        log.warning("skill zh LLM 失败 name=%s err=%s", name, e)
        return None

    text = ""
    try:
        choices = payload.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            text = str(msg.get("content") or "").strip()
    except (AttributeError, IndexError, TypeError):
        text = ""
    if not text:
        return None
    # 去掉可能的代码围栏
    if text.startswith("```"):
        text = re.sub(r"^```(?:\w+)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    if not looks_chinese(text, min_chars=16, min_ratio=0.2):
        log.warning("skill zh LLM 输出中文不足 name=%s", name)
        return None
    return _compact(text, 560)


def ensure_description_zh(
    name: str,
    *,
    description: str = "",
    category: str | None = None,
    category_label: str | None = None,
    display_name: str | None = None,
    force: bool = False,
    use_llm: bool | None = None,
    llm_fn: Callable[..., str | None] | None = None,
) -> str:
    """生成并持久化中文描述；已存在且非 force 则直接返回。"""
    try:
        from skill_meta_store import get_description_zh, set_description_zh
    except ImportError:
        from .skill_meta_store import get_description_zh, set_description_zh  # type: ignore

    n = (name or "").strip()
    if not n:
        return ""
    existing = get_description_zh(n)
    if existing and not force:
        return existing

    draft = draft_description_zh(
        n,
        description=description,
        category=category,
        category_label=category_label,
        display_name=display_name,
    )
    final = draft
    do_llm = zh_llm_enabled() if use_llm is None else bool(use_llm)
    # 原文已是合格中文且非强制定制表：可跳过 LLM
    if do_llm and not (looks_chinese(description) and n not in _KNOWN_CUSTOM):
        polish = llm_fn or polish_description_zh_llm
        try:
            polished = polish(n, draft, description=description)
        except Exception as e:  # noqa: BLE001
            log.warning("skill zh polish 异常 name=%s err=%s", n, e)
            polished = None
        if polished:
            final = polished

    set_description_zh(n, final)
    return final


def attach_description_fields(item: dict[str, Any]) -> dict[str, Any]:
    """写入 description_zh / description_display。"""
    try:
        from skill_meta_store import get_description_zh
    except ImportError:
        from .skill_meta_store import get_description_zh  # type: ignore

    name = str(item.get("name") or "")
    zh = get_description_zh(name) or ""
    raw = str(item.get("description") or "")
    item["description_zh"] = zh
    item["description_display"] = zh or raw
    return item


def maybe_generate_on_install(item: dict[str, Any]) -> dict[str, Any]:
    """安装成功后可选生成中文描述，并刷新展示字段。"""
    if not zh_on_install_enabled():
        return attach_description_fields(item)
    name = str(item.get("name") or "").strip()
    if not name:
        return item
    try:
        ensure_description_zh(
            name,
            description=str(item.get("description") or ""),
            category=str(item.get("category") or "") or None,
            category_label=str(item.get("category_label") or "") or None,
            display_name=str(item.get("display_name") or "") or None,
            force=False,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("install 后生成中文描述失败 name=%s err=%s", name, e)
    return attach_description_fields(item)


def backfill_descriptions_zh(
    skills: list[dict[str, Any]],
    *,
    force: bool = False,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """批量回填；返回汇总。"""
    updated: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for row in skills:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            before = None
            try:
                from skill_meta_store import get_description_zh
            except ImportError:
                from .skill_meta_store import get_description_zh  # type: ignore
            before = get_description_zh(name)
            if before and not force:
                skipped.append(name)
                continue
            ensure_description_zh(
                name,
                description=str(row.get("description") or ""),
                category=str(row.get("category") or "") or None,
                category_label=str(row.get("category_label") or "") or None,
                display_name=str(row.get("display_name") or "") or None,
                force=force,
                use_llm=use_llm,
            )
            updated.append(name)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    return {
        "ok": not errors,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "count_updated": len(updated),
        "count_skipped": len(skipped),
        "count_errors": len(errors),
    }
