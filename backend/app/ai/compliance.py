"""Runtime compliance guards for AI responses (SPEC §3 / §5.7 红线).

Shared by the orchestrator (online) and ``scripts/ai_eval.py`` (offline regression).
"""

from __future__ import annotations

DISCLAIMER_HINT = "不构成投资建议"
DISCLAIMER_SUFFIX = "\n\n⚠️ 本回答基于公开数据，仅供参考，不构成投资建议。"

ADVICE_REDFLAGS = [
    "建议买入",
    "建议卖出",
    "应该买入",
    "应该卖出",
    "必涨",
    "必跌",
    "稳赚",
    "立即买入",
    "马上买入",
    "全仓",
    "清仓",
]

ADVICE_REPLACEMENT = (
    "我无法提供确定性买卖建议或投资建议。"
    "如需了解行情，我可以帮你查询工具返回的客观数据。"
)

ADVICE_STREAM_NOTE = "\n\n【合规提示】我无法提供确定性买卖建议或操作指令。"


def has_disclaimer(text: str) -> bool:
    return DISCLAIMER_HINT in text


def find_advice_flags(text: str) -> list[str]:
    return [w for w in ADVICE_REDFLAGS if w in text]


def enforce_compliance(text: str) -> str:
    """Non-streaming final pass: ensure disclaimer; replace advice-heavy answers."""
    text = text.rstrip()
    if not text:
        text = "暂时无法生成回答。"
    if find_advice_flags(text):
        text = ADVICE_REPLACEMENT
    if not has_disclaimer(text):
        text += DISCLAIMER_SUFFIX
    return text


def stream_compliance_tail(full: str) -> str:
    """Extra SSE chunks to append so streamed output ends compliant."""
    extra: list[str] = []
    if find_advice_flags(full):
        extra.append(ADVICE_STREAM_NOTE)
    combined = full + "".join(extra)
    if not has_disclaimer(combined):
        extra.append(DISCLAIMER_SUFFIX)
    return "".join(extra)
