"""Restricted signal-function validation and subprocess execution.

This is a deliberately small Python subset, not a general Python sandbox.
Custom strategies receive JSON-compatible values and can only return normalized
signals. Imports, attributes, I/O primitives, exceptions, classes and dynamic
code are rejected before the isolated subprocess starts.
"""

from __future__ import annotations

import ast
import json
import math
import subprocess
import sys
import tempfile
import threading
from hashlib import sha256
from typing import Any

from app.core.config import settings
from app.providers.symbols import normalize_a_share_code

PROTOCOL_VERSION = "signal-v1"
ENTRYPOINT = "generate_signals"
MAX_SOURCE_BYTES = 20_000
MAX_AST_NODES = 2_000
MAX_SIGNALS = 500
MAX_REASON_CHARS = 500
_SANDBOX_SLOTS = threading.BoundedSemaphore(
    settings.strategy_sandbox_max_concurrency
)

_ALLOWED_NODES = (
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Expr,
    ast.If,
    ast.For,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.Name,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.keyword,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)
_SAFE_CALLS = frozenset(
    {
        "abs",
        "bool",
        "enumerate",
        "float",
        "get",
        "int",
        "len",
        "max",
        "min",
        "range",
        "round",
        "sorted",
        "sum",
        "zip",
    }
)


class StrategySandboxError(ValueError):
    """Source validation, resource, protocol, or output failure."""


def source_sha256(source: str) -> str:
    return sha256(source.encode("utf-8")).hexdigest()


def validate_source(source: str) -> str:
    normalized = source.replace("\r\n", "\n").strip() + "\n"
    if len(normalized.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise StrategySandboxError(f"策略源码不得超过 {MAX_SOURCE_BYTES} bytes")
    try:
        tree = ast.parse(normalized, mode="exec")
    except SyntaxError as exc:
        raise StrategySandboxError(f"策略源码语法错误: line {exc.lineno}") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise StrategySandboxError("策略源码结构过于复杂")
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(tree.body) != 1 or len(functions) != 1:
        raise StrategySandboxError("源码只能定义一个 generate_signals 函数")
    function = functions[0]
    if function.name != ENTRYPOINT:
        raise StrategySandboxError("入口函数必须命名为 generate_signals")
    if function.decorator_list:
        raise StrategySandboxError("入口函数不允许装饰器")
    if function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
        raise StrategySandboxError("入口函数不允许可变参数或关键字专用参数")
    if [arg.arg for arg in function.args.args] != ["context", "bars"]:
        raise StrategySandboxError("入口参数必须为 context, bars")
    for node in nodes:
        if not isinstance(node, _ALLOWED_NODES):
            raise StrategySandboxError(f"不允许的语法: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise StrategySandboxError("不允许访问私有名称")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_CALLS:
                raise StrategySandboxError("只允许调用受控的纯函数")
    compile(tree, "<strategy>", "exec")
    return normalized


_RUNNER = r"""
import json
import math
import sys

request = json.loads(sys.stdin.read())

try:
    import resource
    limits = request["limits"]
    cpu_seconds = max(int(math.ceil(limits["timeoutSeconds"])), 1)
    memory = int(limits["memoryMb"]) * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
except (ImportError, OSError, ValueError):
    pass

def safe_get(mapping, key, default=None):
    if type(mapping) is not dict:
        return default
    return mapping.get(key, default)

safe_builtins = {
    "abs": abs, "bool": bool, "enumerate": enumerate, "float": float,
    "int": int, "len": len, "max": max, "min": min, "range": range,
    "round": round, "sorted": sorted, "sum": sum, "zip": zip,
    "get": safe_get,
}
namespace = {"__builtins__": safe_builtins}
exec(compile(request["source"], "<strategy>", "exec"), namespace, namespace)
result = namespace["generate_signals"](request["context"], request["bars"])
encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
if len(encoded.encode("utf-8")) > 1048576:
    raise ValueError("strategy output exceeds 1 MiB")
sys.stdout.write(encoded)
"""


def _normalize_output(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {"signals"}:
        raise StrategySandboxError("策略输出必须且只能包含 signals")
    signals = raw["signals"]
    if not isinstance(signals, list) or len(signals) > MAX_SIGNALS:
        raise StrategySandboxError(f"signals 必须是至多 {MAX_SIGNALS} 项的数组")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(signals):
        if not isinstance(item, dict):
            raise StrategySandboxError(f"signals[{index}] 必须是对象")
        if set(item) - {"code", "score", "confidence", "reason"}:
            raise StrategySandboxError(f"signals[{index}] 包含未知字段")
        try:
            code = normalize_a_share_code(str(item["code"]))
            score = float(item["score"])
            confidence = float(item["confidence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategySandboxError(f"signals[{index}] 字段无效") from exc
        if code in seen:
            raise StrategySandboxError(f"signals[{index}] 股票代码重复")
        if not math.isfinite(score) or not -1 <= score <= 1:
            raise StrategySandboxError(f"signals[{index}].score 必须在 [-1,1]")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise StrategySandboxError(
                f"signals[{index}].confidence 必须在 [0,1]"
            )
        reason = str(item.get("reason", "")).strip()
        if len(reason) > MAX_REASON_CHARS:
            raise StrategySandboxError(
                f"signals[{index}].reason 不得超过 {MAX_REASON_CHARS} 字符"
            )
        normalized.append(
            {
                "code": code,
                "score": score,
                "confidence": confidence,
                "reason": reason,
            }
        )
        seen.add(code)
    return {"schemaVersion": 1, "protocolVersion": PROTOCOL_VERSION, "signals": normalized}


def run_source(
    source: str,
    *,
    context: dict[str, Any],
    bars: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    normalized_source = validate_source(source)
    request = json.dumps(
        {
            "source": normalized_source,
            "context": context,
            "bars": bars,
            "limits": {
                "timeoutSeconds": settings.strategy_sandbox_timeout_seconds,
                "memoryMb": settings.strategy_sandbox_memory_mb,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    if not _SANDBOX_SLOTS.acquire(blocking=False):
        raise StrategySandboxError("策略沙箱繁忙，请稍后重试")
    try:
        with tempfile.TemporaryDirectory(prefix="strategy-sandbox-") as directory:
            try:
                completed = subprocess.run(
                    [sys.executable, "-I", "-S", "-c", _RUNNER],
                    input=request,
                    text=True,
                    capture_output=True,
                    cwd=directory,
                    env={"PATH": "", "PYTHONHASHSEED": "0", "TZ": "UTC"},
                    timeout=settings.strategy_sandbox_timeout_seconds,
                    check=False,
                    start_new_session=True,
                )
            except subprocess.TimeoutExpired as exc:
                raise StrategySandboxError("策略执行超时") from exc
    finally:
        _SANDBOX_SLOTS.release()
    if completed.returncode != 0:
        raise StrategySandboxError(
            f"策略执行失败: {completed.stderr.strip()[:300] or completed.returncode}"
        )
    if len(completed.stdout.encode("utf-8")) > 1_048_576:
        raise StrategySandboxError("策略输出超过 1 MiB")
    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise StrategySandboxError("策略输出不是有效 JSON") from exc
    return _normalize_output(output)
