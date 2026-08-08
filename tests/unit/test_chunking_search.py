"""Unit tests for knowledge chunking and search."""

from koebinar.knowledge.chunking import (
    chunk_text,
    estimate_section,
    extract_text_from_pdf_payload,
    extract_text_from_url_payload,
    normalize_whitespace,
    split_paragraphs,
)
from koebinar.knowledge.search import cosine, embed_text, rank_chunks, select_context, tokenize
from koebinar.models import Chunk


def test_normalize_and_paragraphs():
    assert normalize_whitespace(" a  b\n\tc ") == "a b c"
    parts = split_paragraphs("one\n\ntwo\n\n\nthree")
    assert parts == ["one", "two", "three"]


def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_text_respects_max():
    text = "word " * 200
    chunks = chunk_text(text, max_chars=80, overlap=10)
    assert len(chunks) >= 2
    assert all(len(c) <= 80 + 5 for c in chunks)  # soft bound


def test_pdf_and_url_extract():
    pdf = "%PDF-1.4 BT Hello Koebinar World ET"
    assert "Hello" in extract_text_from_pdf_payload(pdf)
    assert "placeholder" in extract_text_from_url_payload("https://example.com/doc")
    assert extract_text_from_url_payload("plain body") == "plain body"


def test_estimate_section():
    assert estimate_section(0, 10) == "intro"
    assert estimate_section(5, 10) == "body"
    assert estimate_section(9, 10) == "outro"
    assert estimate_section(0, 0) == "body"


def test_embed_and_rank():
    a = embed_text("OrcaRouter API gateway for LLM")
    b = embed_text("OrcaRouter routes language models")
    c = embed_text("banana fruit salad recipe")
    assert cosine(a, b) > cosine(a, c)
    chunks = [
        Chunk(id="1", document_id="d", text="OrcaRouter API gateway", embedding=embed_text("OrcaRouter API gateway")),
        Chunk(id="2", document_id="d", text="banana recipe", embedding=embed_text("banana recipe")),
    ]
    ranked = rank_chunks("How does OrcaRouter work?", chunks, top_k=2)
    assert ranked[0][0].id == "1"
    assert len(select_context(ranked, top_n=1)) == 1


def test_tokenize_japanese():
    toks = tokenize("料金とセキュリティについて")
    assert "料金" in toks or any("料" in t for t in toks)
