"""Knowledge ingest and search service."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from koebinar.crypto import generate_id
from koebinar.knowledge.chunking import (
    chunk_text,
    estimate_section,
    extract_text_from_pdf_payload,
    extract_text_from_url_payload,
    normalize_whitespace,
)
from koebinar.knowledge.search import embed_text, rank_chunks, select_context
from koebinar.models import (
    Chunk,
    DocumentStatus,
    KnowledgeCreateRequest,
    KnowledgeDocument,
    SourceType,
)
from koebinar.storage import Store, get_store


class KnowledgeService:
    def __init__(self, store: Optional[Store] = None) -> None:
        self.store = store or get_store()

    def register(self, req: KnowledgeCreateRequest) -> KnowledgeDocument:
        doc_id = generate_id("doc_")
        text = self._extract_text(req)
        storage_uri = self._persist_source(doc_id, req, text)
        chunks = self._build_chunks(doc_id, text)
        doc = KnowledgeDocument(
            id=doc_id,
            title=req.title,
            source_type=req.source_type,
            storage_uri=storage_uri,
            status=DocumentStatus.INDEXED if chunks else DocumentStatus.FAILED,
            chunk_count=len(chunks),
        )
        self.store.documents[doc_id] = doc
        self.store.chunks[doc_id] = chunks
        return doc

    def get(self, document_id: str) -> Optional[KnowledgeDocument]:
        return self.store.documents.get(document_id)

    def list_documents(self) -> list[KnowledgeDocument]:
        return list(self.store.documents.values())

    def get_chunks(self, document_ids: Optional[list[str]] = None) -> list[Chunk]:
        if document_ids is None:
            ids = list(self.store.chunks.keys())
        else:
            ids = document_ids
        out: list[Chunk] = []
        for did in ids:
            out.extend(self.store.chunks.get(did, []))
        return out

    def search(
        self,
        query: str,
        *,
        document_ids: Optional[list[str]] = None,
        top_k: int = 10,
        top_n: int = 5,
    ) -> list[tuple[Chunk, float]]:
        chunks = self.get_chunks(document_ids)
        ranked = rank_chunks(query, chunks, top_k=top_k)
        return select_context(ranked, top_n=top_n)

    def _extract_text(self, req: KnowledgeCreateRequest) -> str:
        if req.source_type == SourceType.PDF:
            return extract_text_from_pdf_payload(req.content)
        if req.source_type == SourceType.URL:
            return extract_text_from_url_payload(req.content)
        return normalize_whitespace(req.content)

    def _persist_source(self, doc_id: str, req: KnowledgeCreateRequest, text: str) -> str:
        base = self.store.settings.data_dir / "knowledge" / doc_id
        base.mkdir(parents=True, exist_ok=True)
        path = base / "source.txt"
        path.write_text(text, encoding="utf-8")
        meta = base / "meta.json"
        meta.write_text(
            __import__("json").dumps(
                {"title": req.title, "source_type": req.source_type.value, "metadata": req.metadata},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return str(path)

    def _build_chunks(self, doc_id: str, text: str) -> list[Chunk]:
        pieces = chunk_text(text)
        total = len(pieces)
        chunks: list[Chunk] = []
        for i, piece in enumerate(pieces):
            chunks.append(
                Chunk(
                    id=generate_id("chk_"),
                    document_id=doc_id,
                    text=piece,
                    section=estimate_section(i, total),
                    embedding=embed_text(piece),
                )
            )
        return chunks
