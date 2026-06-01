"""可插拔文本向量化（RAG）。

后端经 ``settings.embedding_provider`` 选择：
- ``local``：本地 sentence-transformers（默认 bge-small-zh-v1.5，免费离线，懒加载）
- ``api``：OpenAI 兼容的 embedding 接口（需 ``embedding_api_base`` / ``embedding_api_key``）

bge 中文检索建议：查询侧加指令前缀，文档侧不加；输出做 L2 归一化（配合余弦距离）。
"""

from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# bge-zh 系列推荐的检索查询指令前缀
_BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

_local_model = None


def _is_bge() -> bool:
    return "bge" in settings.embedding_model.lower()


def _get_local_model():
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("加载本地 embedding 模型：%s（首次会下载）", settings.embedding_model)
        _local_model = SentenceTransformer(settings.embedding_model)
    return _local_model


def _embed_local(texts: list[str]) -> list[list[float]]:
    model = _get_local_model()
    vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def _embed_api(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_api_base or None,
    )
    resp = client.embeddings.create(model=settings.embedding_model, input=texts)
    return [d.embedding for d in resp.data]


def embed_texts(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """编码文本为向量。``is_query=True`` 时对 bge 模型加检索指令前缀。"""
    if not texts:
        return []
    payload = texts
    if is_query and settings.embedding_provider == "local" and _is_bge():
        payload = [_BGE_QUERY_INSTRUCTION + t for t in texts]
    if settings.embedding_provider == "api":
        return _embed_api(payload)
    return _embed_local(payload)


def embed_query(text: str) -> list[float]:
    return embed_texts([text], is_query=True)[0]


def warm() -> None:
    """预加载本地 embedding 模型（首次会下载）。供启动时后台线程调用，避免首个
    早报/问答请求被模型加载阻塞。失败仅记录、不抛出（离线环境照常降级）。"""
    if settings.embedding_provider != "local":
        return
    try:
        _get_local_model()
        logger.info("本地 embedding 模型预热完成：%s", settings.embedding_model)
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding 预热失败（RAG 将在调用时重试/降级）：%s", exc)


def warm_in_background() -> None:
    """以守护线程预热，绝不阻塞启动。"""
    import threading

    threading.Thread(target=warm, name="embedding-warm", daemon=True).start()
