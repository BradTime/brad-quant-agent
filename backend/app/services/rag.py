"""RAG 检索服务（Phase A）。

把语料（新闻 / 历史早报等）切块 + 向量化后落 ``documents`` 表（pgvector），
并提供基于余弦距离的语义检索 ``retrieve``。供 AI 工具 ``search_knowledge`` 与早报装配复用。
"""

from __future__ import annotations

import hashlib
import json
import logging
import operator
import re
from datetime import datetime
from functools import reduce

from sqlalchemy import case, delete, or_, select, text

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
    """切块向量化并 staging 后交换（先建行再删旧插新）。返回**实际写入**块数。

    向量数/维度与切块不一致时**不删旧索引**，抛 ``ValueError``（H20）。
    """
    chunks = _chunk(text)
    if not chunks:
        return 0
    vectors = embeddings.embed_texts(chunks, is_query=False)
    if len(vectors) != len(chunks):
        raise ValueError(
            f"embedding count mismatch: chunks={len(chunks)} vectors={len(vectors)} "
            f"source={source} ref_id={ref_id}"
        )
    expected_dim = int(settings.embedding_dim)
    for i, vec in enumerate(vectors):
        if not isinstance(vec, (list, tuple)) or len(vec) != expected_dim:
            got = len(vec) if isinstance(vec, (list, tuple)) else type(vec).__name__
            raise ValueError(
                f"embedding dim mismatch at chunk {i}: expected {expected_dim}, got {got} "
                f"source={source} ref_id={ref_id}"
            )

    meta_json = json.dumps(meta, ensure_ascii=False, default=str) if meta else None
    staged = [
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
        for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True))
    ]
    with SessionLocal() as session:
        session.execute(
            delete(Document).where(Document.source == source, Document.ref_id == ref_id)
        )
        session.add_all(staged)
        session.commit()
    return len(staged)


def _already_indexed(session, source: str, ref_ids: list[str]) -> set[str]:
    if not ref_ids:
        return set()
    rows = session.execute(
        select(Document.ref_id)
        .where(Document.source == source, Document.ref_id.in_(ref_ids))
        .distinct()
    ).scalars()
    return {r for r in rows if r}


_RRF_K = 60  # RRF 融合常数（经验值，抑制单路高排名的过度主导）
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}")
_STOPWORDS = {"什么", "怎么", "为什么", "如何", "哪些", "可能", "影响", "情况", "相关", "公司", "股票"}


def _keywords(query: str, limit: int = 6) -> list[str]:
    """从查询粗提关键词（中文连续片段 / 英文数字串，去停用、去重保序）。

    无中文分词器，按字符片段近似即可——召回兜底仍由向量侧保证。
    """
    out: list[str] = []
    for tok in _TOKEN_RE.findall(query):
        if tok in _STOPWORDS or tok in out:
            continue
        out.append(tok)
    return out[:limit]


def _set_ef_search(session) -> None:
    """设置 HNSW 检索精度（仅当建了 HNSW 索引才有意义）；旧版本/无索引时静默忽略。"""
    try:
        session.execute(text(f"SET LOCAL hnsw.ef_search = {int(settings.rag_hnsw_ef_search)}"))
    except Exception:  # noqa: BLE001
        pass


def _apply_public_scope(stmt):
    """Exclude user-personalized briefs from the shared retrieval corpus."""
    global_brief_ids = select(MorningBrief.id).where(
        MorningBrief.user_id.is_(None),
        MorningBrief.status == "ready",
    )
    return stmt.where(
        or_(
            Document.source != "brief",
            Document.ref_id.in_(global_brief_ids),
        )
    )


def _vector_rows(session, qvec, limit: int, source: str | None) -> list[tuple]:
    distance = Document.embedding.cosine_distance(qvec).label("distance")
    stmt = _apply_public_scope(select(Document, distance))
    if source:
        stmt = stmt.where(Document.source == source)
    stmt = stmt.order_by(distance).limit(limit)
    return list(session.execute(stmt).all())


def _keyword_rows(session, tokens: list[str], limit: int, source: str | None) -> list:
    """关键词召回：title/chunk 命中即入选，按命中权重（标题>正文）排序。"""
    if not tokens:
        return []
    conds = []
    score_terms = []
    for t in tokens:
        like = f"%{t}%"
        conds.append(Document.chunk.ilike(like))
        conds.append(Document.title.ilike(like))
        score_terms.append(case((Document.title.ilike(like), 2), else_=0))
        score_terms.append(case((Document.chunk.ilike(like), 1), else_=0))
    hit = reduce(operator.add, score_terms)
    stmt = _apply_public_scope(select(Document).where(or_(*conds)))
    if source:
        stmt = stmt.where(Document.source == source)
    stmt = stmt.order_by(hit.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def _row_to_dict(doc, dist) -> dict:
    return {
        "source": doc.source,
        "code": doc.code,
        "title": doc.title,
        "chunk": doc.chunk,
        "publishedAt": doc.published_at.isoformat() if doc.published_at else None,
        "score": round(1.0 - float(dist), 4) if dist is not None else None,
    }


def retrieve(query: str, k: int | None = None, source: str | None = None) -> list[dict]:
    """检索：默认向量 + 关键词混合（RRF 融合）；经 ``rag_hybrid_enabled`` 可关闭为纯向量。

    **硬降级**：embedding 加载/编码、pgvector 扩展缺失、documents 表未建、维度不匹配等
    任何失败都不应影响调用方（早报/问答）——统一记录 warning 并返回 []。
    """
    if not settings.rag_enabled:
        return []
    query = (query or "").strip()
    if not query:
        return []
    k = k or settings.rag_top_k
    try:
        qvec = embeddings.embed_query(query)
        with SessionLocal() as session:
            _set_ef_search(session)
            if not settings.rag_hybrid_enabled:
                rows = _vector_rows(session, qvec, k, source)
                return [_row_to_dict(doc, dist) for doc, dist in rows]
            cand = max(settings.rag_hybrid_candidates, k)
            vec = _vector_rows(session, qvec, cand, source)
            kw = _keyword_rows(session, _keywords(query), cand, source)
    except Exception as exc:  # noqa: BLE001  (检索为增强项，失败即降级为空)
        logger.warning("RAG 检索失败，降级为空：%s", exc)
        return []

    # RRF 融合：两路排名各按 1/(K+rank) 累加，得分高者优先（向量保语义、关键词保字面命中）
    scores: dict[str, float] = {}
    docs: dict[str, object] = {}
    dists: dict[str, float] = {}
    for rank, (doc, dist) in enumerate(vec):
        scores[doc.id] = scores.get(doc.id, 0.0) + 1.0 / (_RRF_K + rank)
        docs[doc.id] = doc
        dists[doc.id] = dist
    for rank, doc in enumerate(kw):
        scores[doc.id] = scores.get(doc.id, 0.0) + 1.0 / (_RRF_K + rank)
        docs.setdefault(doc.id, doc)
    ordered = sorted(scores, key=lambda i: scores[i], reverse=True)[:k]
    return [_row_to_dict(docs[i], dists.get(i)) for i in ordered]


# ---------- 回填（把已落库语料灌入向量库） ----------


def backfill_news(limit: int = 500, *, skip_indexed: bool = True) -> int:
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(NewsItem).order_by(NewsItem.fetched_at.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
        indexed = (
            _already_indexed(session, "news", [r.id for r in rows])
            if skip_indexed
            else set()
        )
    total = 0
    skipped = 0
    for r in rows:
        if r.id in indexed:
            skipped += 1
            continue
        body = r.title or ""
        if r.summary:
            body += "\n" + r.summary
        try:
            total += index_document(
                source="news",
                ref_id=r.id,
                title=r.title or "",
                text=body,
                code=r.code,
                published_at=r.published_at,
                meta={"url": r.url, "sourceName": r.source_name},
            )
        except ValueError as exc:
            logger.warning("RAG 回填新闻跳过 %s：%s", r.id, exc)
    logger.info(
        "RAG 回填新闻：候选 %d 篇，跳过已索引 %d，写入 %d 块",
        len(rows),
        skipped,
        total,
    )
    return total


def backfill_briefs(limit: int = 60, *, skip_indexed: bool = True) -> int:
    with SessionLocal() as session:
        private_brief_ids = select(MorningBrief.id).where(
            MorningBrief.user_id.is_not(None)
        )
        session.execute(
            delete(Document).where(
                Document.source == "brief",
                Document.ref_id.in_(private_brief_ids),
            )
        )
        rows = list(
            session.execute(
                select(MorningBrief)
                .where(
                    MorningBrief.status == "ready",
                    MorningBrief.user_id.is_(None),
                )
                .order_by(MorningBrief.generated_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        indexed = (
            _already_indexed(session, "brief", [r.id for r in rows])
            if skip_indexed
            else set()
        )
        session.commit()
    total = 0
    skipped = 0
    for r in rows:
        if r.id in indexed:
            skipped += 1
            continue
        published = None
        if r.generated_at:
            published = r.generated_at.replace(tzinfo=None)
        try:
            total += index_document(
                source="brief",
                ref_id=r.id,
                title=r.title or "",
                text=r.content or "",
                code=None,
                published_at=published,
                meta={"tradeDate": r.trade_date.isoformat() if r.trade_date else None},
            )
        except ValueError as exc:
            logger.warning("RAG 回填早报跳过 %s：%s", r.id, exc)
    logger.info(
        "RAG 回填历史早报：候选 %d 篇，跳过已索引 %d，写入 %d 块",
        len(rows),
        skipped,
        total,
    )
    return total


def backfill_all() -> dict:
    return {"news": backfill_news(), "briefs": backfill_briefs()}
