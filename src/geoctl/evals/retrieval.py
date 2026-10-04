"""Retrieval: chunk, embed, top-k (EVALS §3.3, ADR-011).

This is the stage that makes the eval discriminative. Handing a model the whole
page measures the model, not the site: a pricing table at the top of a page and
one buried in the middle are equally available to a model given the full
document and behave nothing alike inside a real retrieval stack. So the eval
retrieves rather than pastes.

The consequence is that the eval is deliberately harsher than whole-page
context, which is the property this project can promise and verify. It cannot
match any vendor's pipeline exactly, and does not claim to.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

CHUNK_TARGET_TOKENS = 400
CHUNK_OVERLAP_PCT = 10
# Below this many chunks, chunking has nothing to select between, so the eval
# passes the whole page and *says so* — that is where the metric loses resolution.
MIN_CHUNKS = 3

DEFAULT_EMBEDDING = "openai/text-embedding-3-small"

_WS = re.compile(r"\s+")


@dataclass
class Chunk:
    text: str
    index: int
    heading_path: str = ""
    tokens: int = 0


RetrievalMode = Literal["chunked", "whole_page"]


@dataclass
class RetrievalResult:
    chunks: list[Chunk] = field(default_factory=list)
    mode: RetrievalMode = "chunked"
    top_k: int = 5
    chunk_target_tokens: int = CHUNK_TARGET_TOKENS
    chunk_overlap_pct: int = CHUNK_OVERLAP_PCT
    embedding_model: str = DEFAULT_EMBEDDING

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_text(
    text: str,
    *,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_pct: int = CHUNK_OVERLAP_PCT,
) -> list[Chunk]:
    """Split on heading and paragraph boundaries, never mid-sentence where avoidable.

    Heading-aware splitting matters because headings are the anchors retrieval
    systems key on, and because STR-005 (a broken hierarchy) directly degrades
    the chunks this produces.
    """
    if not text.strip():
        return []

    blocks = _blocks(text)
    if not blocks:
        return []

    chunks: list[Chunk] = []
    current: list[str] = []
    current_len = 0
    heading = ""

    for block_heading, block_text in blocks:
        if approx_tokens(block_text) > target_tokens:
            # Flush, then split an oversized paragraph on sentence boundaries.
            if current:
                chunks.append(
                    Chunk(
                        text="\n\n".join(current),
                        index=len(chunks),
                        heading_path=heading,
                        tokens=approx_tokens(" ".join(current)),
                    )
                )
                current, current_len = [], 0
            for piece in _split_long(block_text, target_tokens):
                heading = block_heading or heading
                chunks.append(
                    Chunk(
                        text=piece,
                        index=len(chunks),
                        heading_path=heading,
                        tokens=approx_tokens(piece),
                    )
                )
            continue

        if current_len + approx_tokens(block_text) > target_tokens and current:
            joined = "\n\n".join(current)
            chunks.append(
                Chunk(
                    text=joined,
                    index=len(chunks),
                    heading_path=heading,
                    tokens=approx_tokens(joined),
                )
            )
            current = _overlap_tail(current, overlap_pct, target_tokens)
            current_len = approx_tokens(" ".join(current))
        if block_heading:
            heading = block_heading
        current.append(block_text)
        current_len += approx_tokens(block_text)

    if current:
        joined = "\n\n".join(current)
        chunks.append(
            Chunk(
                text=joined, index=len(chunks), heading_path=heading, tokens=approx_tokens(joined)
            )
        )
    return chunks


def _blocks(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading_path, block) pairs."""
    out: list[tuple[str, str]] = []
    headings: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            out.append((" > ".join(headings[-3:]), "\n".join(buffer).strip()))
            buffer.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            headings.append(stripped.lstrip("#").strip())
            del headings[: max(0, len(headings) - level)]
        elif not stripped:
            continue
        else:
            buffer.append(stripped)
    flush()
    return [(h, b) for h, b in out if b]


def _split_long(text: str, target_tokens: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in sentences:
        n = approx_tokens(sentence)
        if size + n > target_tokens and current:
            pieces.append(" ".join(current))
            current, size = [], 0
        current.append(sentence)
        size += n
    if current:
        pieces.append(" ".join(current))
    return pieces


def _overlap_tail(parts: list[str], overlap_pct: int, target_tokens: int) -> list[str]:
    """Carry the tail of the previous chunk into the next, so a fact split across
    a boundary is retrievable from either side."""
    if overlap_pct <= 0:
        return []
    budget = max(1, int(target_tokens * overlap_pct / 100))
    tail: list[str] = []
    size = 0
    for part in reversed(parts):
        n = approx_tokens(part)
        if size + n > budget:
            break
        tail.insert(0, part)
        size += n
    return tail


def embed(texts: list[str], model: str = DEFAULT_EMBEDDING) -> list[list[float]]:
    """Embed a batch. One cheap call per page (EVALS §3.3)."""
    if not texts:
        return []
    import litellm

    response = litellm.embedding(model=model, input=texts)
    data = getattr(response, "data", None) or []
    return [[float(x) for x in item["embedding"]] for item in data]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def lexical_scores(question: str, chunks: list[Chunk]) -> list[float]:
    """Deterministic fallback when no embedding provider is available.

    Reported in the output as a different retrieval mode so scores are never
    silently compared across incomparable configurations.
    """
    q = set(_WS.sub(" ", question.lower()).split())
    if not q:
        return [0.0] * len(chunks)
    out = []
    for chunk in chunks:
        terms = set(_WS.sub(" ", (chunk.heading_path + " " + chunk.text).lower()).split())
        if not terms:
            out.append(0.0)
            continue
        overlap = len(q & terms)
        out.append(overlap / math.sqrt(len(q) * len(terms)))
    return out


def retrieve(
    question: str,
    chunks: list[Chunk],
    *,
    top_k: int = 5,
    vectors: list[list[float]] | None = None,
    query_vector: list[float] | None = None,
) -> list[tuple[Chunk, float]]:
    """Top-k chunks for one question, best first."""
    if not chunks:
        return []
    if vectors and query_vector:
        scores = [cosine(query_vector, v) for v in vectors]
    else:
        # Lexical fallback. Deterministic, so it is still reproducible; the
        # reported embedding_model says which was used, so scores from the two
        # are never silently compared.
        scores = lexical_scores(question, chunks)
    ranked = sorted(zip(chunks, scores, strict=True), key=lambda pair: -pair[1])
    return ranked[:top_k]


def prepare(
    text: str,
    *,
    top_k: int = 5,
    embedding_model: str = DEFAULT_EMBEDDING,
    embed_fn: Any | None = None,
    min_chunks: int = MIN_CHUNKS,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_pct: int = CHUNK_OVERLAP_PCT,
) -> tuple[RetrievalResult, list[list[float]] | None]:
    """Chunk a crawler view and embed it once. Returns vectors for reuse.

    The whole_page fallback is explicit in the result: with fewer than
    `min_chunks` the metric loses the resolution that makes it useful, and the
    report has to say so (EVALS §3.3).
    """
    chunks = chunk_text(text, target_tokens=target_tokens, overlap_pct=overlap_pct)
    if len(chunks) < min_chunks:
        if text.strip():
            chunks = [Chunk(text=text.strip(), index=0, tokens=approx_tokens(text))]
        mode: RetrievalMode = "whole_page"
    else:
        mode = "chunked"

    vectors: list[list[float]] | None = None
    if embed_fn is not None and chunks:
        try:
            vectors = embed_fn([c.text for c in chunks], embedding_model)
        except Exception:
            vectors = None

    result = RetrievalResult(
        chunks=chunks,
        mode=mode,
        top_k=top_k,
        chunk_target_tokens=target_tokens,
        chunk_overlap_pct=overlap_pct,
        embedding_model=embedding_model if vectors else "lexical (no embedding provider)",
    )
    return result, vectors


def span_retrieved(span: str, chunks: list[Chunk]) -> bool:
    """Was the question's source span among the retrieved chunks?

    This is the primary diagnostic (EVALS §3.6): it separates extraction failure
    from writing failure, so a user knows which problem they have.
    """
    if not span:
        return False
    needle = _WS.sub(" ", span.lower()).strip()[:120]
    if not needle:
        return False
    # Compare on a distinctive fragment: a 120-character window can straddle a
    # whitespace difference and produce a false negative.
    words = needle.split()
    probe = " ".join(words[: min(12, len(words))])
    for chunk in chunks:
        hay = _WS.sub(" ", chunk.text.lower())
        if probe and probe in hay:
            return True
        if needle in hay:
            return True
    return False
