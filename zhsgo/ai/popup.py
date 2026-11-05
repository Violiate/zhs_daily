"""弹题作答：把“服务端已给答案”和“需要模型补答”两条路合并。

智慧树弹题（popupAnswer）返回的 `testQuestion` 通常带 `questionOptions`，
其中 `result == "1"` 的选项就是正确答案 —— 这种情况下不需要模型。
但有两类题会缺答案：

  * 填空题（questionType == 3）：选项里可能是候选词，提交时前端传的是
    `content` 而不是 `id`；
  * 部分新题型/服务端裁剪：`result` 全为空。

这里对第一类按 content 提交，对第二类调用已配置的 LLM（默认智慧树自带
大模型，不需要额外 key），最后才退化为启发式选择，保证弹窗不会卡住视频。
"""
from __future__ import annotations

import html
import re
from typing import Any, List, Optional, Sequence

from ..logger import get as log
from .client import Answerer
from .prompts import TYPE_JUDGE, TYPE_MULTIPLE, TYPE_SINGLE, build_fill_prompt

TYPE_FILL = 3
TYPE_FILL_NAMES = {3, 5, 6, 7, 8, 9, 10, 11, 12, 13}


def strip_html(text: Any) -> str:
    raw = str(text or "")
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"\s+", " ", raw).strip()


def _option_text(option: Any) -> str:
    for key in ("content", "optionContent", "name", "title", "answer"):
        value = getattr(option, key, None)
        if value is None and isinstance(option, dict):
            value = option.get(key)
        if value:
            return strip_html(value)
    return ""


def _option_id(option: Any) -> str:
    for key in ("id", "optionId", "questionOptionId"):
        value = getattr(option, key, None)
        if value is None and isinstance(option, dict):
            value = option.get(key)
        if value is not None:
            return str(value)
    return ""


def _option_result(option: Any) -> str:
    for key in ("result", "isCorrect", "correct", "right"):
        value = getattr(option, key, None)
        if value is None and isinstance(option, dict):
            value = option.get(key)
        if value is not None:
            return str(value).strip().lower()
    return ""


def _field(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value is None and isinstance(obj, dict):
            value = obj.get(name)
        if value is not None:
            return value
    return default


class PopupSolver:
    def __init__(self, answerer: Answerer, ctx: Any, context_name: str = ""):
        self.answerer = answerer
        self.ctx = ctx
        self.context_name = context_name

    # ------------------------------------------------------------------ 入口

    def solve(self, quiz: Any) -> str:
        """返回 saveLessonPopupExamSaveAnswer 的 `answer` 字段。

        多选/单选：逗号分隔的 option id；
        填空：逗号分隔的答案文本。
        """
        raw_type = _field(quiz, "questionType", "type", default=0)
        type_name = ""
        if isinstance(raw_type, dict):
            # 线上弹题返回的是 {"id": 14, "name": "判断题", "inputType": "radio"}
            type_name = str(raw_type.get("name") or "")
            raw_type = raw_type.get("id") or raw_type.get("value") or 0
        try:
            qtype = int(raw_type or 0)
        except (TypeError, ValueError):
            qtype = 0
        is_fill = qtype in TYPE_FILL_NAMES or "填空" in type_name
        options = list(_field(quiz, "questionOptions", "options", default=[]) or [])
        question = strip_html(_field(quiz, "content", "question", "title", "stem",
                                     "name", default=""))

        marked = [o for o in options if _option_result(o) in ("1", "true", "yes", "y")]
        if marked:
            if is_fill:
                values = [_option_text(o) for o in marked]
                values = [v for v in values if v]
                if values:
                    return ",".join(values)
            ids = [_option_id(o) for o in marked]
            ids = [i for i in ids if i]
            if ids:
                return ",".join(ids)

        # 有些题型不在 questionOptions[].result 里标答案，而是单独给
        # answerRight / answer。能对上选项就转成 id，填空直接当文本。
        right = _field(quiz, "answerRight", "correctAnswer", "answer")
        if right:
            values = right if isinstance(right, (list, tuple)) else re.split(r"[,，;；#@#]+", str(right))
            values = [strip_html(v) for v in values if strip_html(v)]
            if values:
                if is_fill:
                    return ",".join(values)
                ids = []
                for value in values:
                    for option in options:
                        if value in (_option_id(option), _option_text(option)):
                            ids.append(_option_id(option))
                            break
                if ids:
                    return ",".join(ids)

        # 服务端没给答案：填空题走文本模型，选择题走选项模型
        if is_fill or (not options and question):
            return self._fill(question, options, qtype)

        choices = [{"id": _option_id(o), "content": _option_text(o)} for o in options]
        choices = [c for c in choices if c["id"]]
        if not choices:
            return ""

        if getattr(self.answerer, "backend", None) is None:
            # 没有模型时不要随机：单选/判断取第一个，多选取全部。
            if qtype == TYPE_MULTIPLE:
                return ",".join(c["id"] for c in choices)
            return choices[0]["id"]

        try:
            result = self.answerer.answer(qtype or TYPE_SINGLE, question, choices)
            if result.ids:
                log().info(f"弹题 {qtype} 由 {result.source} 作答: {result.ids}")
                return ",".join(str(i) for i in result.ids)
        except Exception as exc:  # 防御：Answerer 内部已有回退，这里只兜底
            log().warning(f"弹题模型作答失败，使用启发式: {exc}")

        if qtype == TYPE_MULTIPLE:
            return ",".join(c["id"] for c in choices)
        return choices[0]["id"]

    # ------------------------------------------------------------------ 填空

    def _fill(self, question: str, options: Sequence[Any], qtype: int) -> str:
        option_texts = [t for t in (_option_text(o) for o in options) if t]
        backend = getattr(self.answerer, "backend", None)
        if backend is not None and question:
            try:
                prompt = build_fill_prompt(self.ctx, question, option_texts)
                text = backend.complete(prompt)
                parsed = self._parse_fill(text)
                if parsed:
                    log().info(f"填空题由模型作答: {parsed[:80]}")
                    return parsed
            except Exception as exc:
                log().warning(f"填空题模型作答失败，使用启发式: {exc}")

        # 没有模型 / 模型失败：如果选项本身就是候选答案，取第一个；
        # 否则提交一个占位文本，让前端把弹窗关掉，不阻塞视频。
        if option_texts:
            return option_texts[0]
        return "略"

    @staticmethod
    def _parse_fill(text: str) -> str:
        match = re.search(r"```answer\s*\n?(.*?)\n?```", text or "", re.DOTALL)
        raw = match.group(1) if match else (text or "")
        raw = strip_html(raw)
        # 多个空用 #@# / 换行 / 分号分隔，统一成前端使用的逗号
        parts = re.split(r"#@#|[\r\n;；]+", raw)
        parts = [p.strip(" \t,，。") for p in parts if p.strip(" \t,，。")]
        if not parts:
            return ""
        return ",".join(parts[:8])
