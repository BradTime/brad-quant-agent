"""RAG 检索服务（Phase A）。

把语料（新闻 / 历史早报等）切块 + 向量化后落 ``documents`` 表（pgvector），
并提供基于余弦距离的语义检索 ``retrieve``。供 AI 工具 ``search_knowledge`` 与早报装配复用。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from sqlalchemy import delete, select

from app.ai import embeddings
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.brief import MorningBrief
from app.models.document import Document
from app.models.extra import NewsItem

logger = logging.getLogger(__name__)


def _sha1(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _chunk(text: str, size: int = 380, overlap: int = 60) -> list[str]:
    """按字符切块（中文友好）。短文本整体返回。"""
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    out: list[str] = []
    start = 0
    step = max(size - overlap, 1)
    while start < len(text):
        out.append(text[start : start + size])
        start += step
    return out


def index_document(
    source: str,
    ref_id: str,
    title: str,
    text: str,
    code: str | None = None,
    published_at: datetime | None = None,
    meta: dict | None = None,
) -> int:
    """把单篇语料切块向量化并 upsert（按 source+ref_id 先删后插，幂等）。返回写入块数。"""
    chunks = _chunk(text)
    if not chunks:
        return 0
    vectors = embeddings.embed_texts(chunks, is_query=False)
    meta_json = json.dumps(meta, ensure_ascii=False, default=str) if meta else None
    with SessionLocal() as session:
        session.execute(
            delete(Document).where(Document.source == source, Document.ref_id == ref_id)
        )
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            session.add(
                Document(
                    id=_sha1(source, ref_id, str(i)),
                    source=source,
                    ref_id=ref_id,
                    code=code,
                    title=title[:512],
                    chunk=chunk,
                    chunk_index=i,
                    embedding=vec,
                    published_at=published_at,
                    meta=meta_json,
                )
            )
        session.commit()
    return len(chunks)


def retrieve(query: str, k: int | None = None, source: str | None = None) -> list[dict]:
    """语义检索：返回最相关的若干文档块（含相似度分数）。"""
    query = (query or "").strip()
    if not query:
        return []
    k = k or settings.rag_top_k
    try:
        qvec = embeddings.embed_query(query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询向量化失败（RAG 跳过）：%s", exc)
        return []

    with SessionLocal() as session:
        distance = Document.embedding.cosine_distance(qvec).label("distance")
        stmt = select(Document, distance)
        if source:
            stmt = stmt.where(Document.source == source)
        stmt = stmt.order_by(distance).limit(k)
        rows = session.execute(stmt).all()

    out: list[dict] = []
    for doc, dist in rows:
        out.append(
            {
                "source": doc.source,
                "code": doc.code,
                "title": doc.title,
                "chunk": doc.chunk,
                "publishedAt": doc.published_at.isoformat() if doc.published_at else None,
                "score": round(1.0 - float(dist), 4),
            }
        )
    return out


# ---------- 回填（把已落库语料灌入向量库） ----------


def backfill_news(limit: int = 500) -> int:
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(NewsItem).order_by(NewsItem.fetched_at.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
    total = 0
    for r in rows:
        body = r.title or ""
        if r.summary:
            body += "\n" + r.summary
        total += index_document(
            source="news",
            ref_id=r.id,
            title=r.title or "",
            text=body,
            code=r.code,
            published_at=r.published_at,
            meta={"url": r.url, "sourceName": r.source_name},
        )
    logger.info("RAG 回填新闻：%d 篇 → %d 块", len(rows), total)
    return total


def backfill_briefs(limit: int = 60) -> int:
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(MorningBrief)
                .where(MorningBrief.status == "ready")
                .order_by(MorningBrief.generated_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
    total = 0
    for r in rows:
        published = None
        if r.generated_at:
            published = r.generated_at.replace(tzinfo=None)
        total += index_document(
            source="brief",
            ref_id=r.id,
            title=r.title or "",
            text=r.content or "",
            code=None,
            published_at=published,
            meta={"tradeDate": r.trade_date.isoformat() if r.trade_date else None},
        )
    logger.info("RAG 回填历史早报：%d 篇 → %d 块", len(rows), total)
    return total


def backfill_all() -> dict:
    return {"news": backfill_news(), "briefs": backfill_briefs()}
