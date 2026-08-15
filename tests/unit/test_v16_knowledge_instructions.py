"""Regression tests for the v1.6 knowledge binding and instructions contract."""

from __future__ import annotations

import json

from koebinar.models import (
    Lang,
    QuestionCreateRequest,
    QuestionStatus,
    Style,
    Template,
    Webinar,
)
from koebinar.pipeline.steps import GenerationSteps
from koebinar.qa.service import QAService
from tests.helpers import seed_attested_voice_ref


class RecordingKnowledge:
    def __init__(self) -> None:
        self.document_filters: list[list[str] | None] = []

    def search(self, _query: str, *, document_ids=None, top_k=10, top_n=5):
        self.document_filters.append(document_ids)
        return []


def _webinar(*, instructions: str, document_ids: list[str] | None = None) -> Webinar:
    return Webinar(
        id="web_v16",
        theme="安全なAI導入",
        audience="経営層",
        duration_min=3,
        lang=Lang.JA,
        template=Template.TECH,
        style=Style.KEYNOTE,
        voice_id="voice",
        instructions=instructions,
        document_ids=document_ids or [],
    )


def test_generation_keeps_instructions_separate_and_empty_documents_explicit(settings, store):
    knowledge = RecordingKnowledge()
    steps = GenerationSteps(store=store, settings=settings, knowledge=knowledge)
    payloads: dict[str, dict] = {}

    def fake_call(messages, purpose):
        payloads[purpose] = json.loads(messages[1]["content"])
        if purpose == "outline":
            return {"sections": [{"title": "導入", "purpose": "説明"}]}
        return {"slides": [{"title": "導入", "narration": "本文", "references": []}]}

    steps._call_json = fake_call  # type: ignore[method-assign]
    webinar = _webinar(instructions="結論を先に。競合名は出さない。")

    outline = steps.generate_outline(webinar)
    steps.generate_script(webinar, {"slides": [{"title": "導入", "bullets": []}]})

    assert payloads["outline"]["operator_instructions"] == webinar.instructions
    assert payloads["script"]["operator_instructions"] == webinar.instructions
    assert "operator_instructions" not in payloads["outline"]["kb"]
    assert knowledge.document_filters == [[], []]

    changed = _webinar(instructions="技術詳細を優先する。")
    changed_outline = steps.generate_outline(changed)
    assert outline["input_hash"] != changed_outline["input_hash"]


def test_api_persists_document_provenance_and_webinar_instructions(client, store):
    seed_attested_voice_ref(store, "voice-knowledge")
    document = client.post(
        "/api/v1/knowledge/documents",
        json={
            "title": "提案資料.pptx",
            "source_type": "text",
            "content": "提案資料から抽出したテキストです。",
            "metadata": {"original_format": "pptx", "filename": "提案資料.pptx"},
        },
    )
    assert document.status_code == 200
    assert document.json()["metadata"] == {
        "original_format": "pptx",
        "filename": "提案資料.pptx",
    }

    webinar = client.post(
        "/api/v1/webinars",
        json={
            "theme": "提案の要点",
            "voice_id": "voice-knowledge",
            "instructions": "導入効果を数字で強調する",
            "document_ids": [document.json()["id"]],
            "auto_run": False,
        },
    )
    assert webinar.status_code == 200
    assert webinar.json()["instructions"] == "導入効果を数字で強調する"

    fetched = client.get(f"/api/v1/webinars/{webinar.json()['id']}")
    assert fetched.json()["instructions"] == webinar.json()["instructions"]


def test_qa_with_no_selected_documents_does_not_search_other_webinar_data(settings, store):
    knowledge = RecordingKnowledge()
    webinar = _webinar(instructions="")
    store.webinars[webinar.id] = webinar
    qa = QAService(store=store, settings=settings, knowledge=knowledge)

    question = qa.ask(
        QuestionCreateRequest(webinar_id=webinar.id, message="別資料の価格を教えてください")
    )

    assert knowledge.document_filters == [[]]
    assert question.status == QuestionStatus.HELD
