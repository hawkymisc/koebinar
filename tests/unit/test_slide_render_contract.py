from unittest.mock import patch

from koebinar.models import Lang, Style, Template, Webinar
from koebinar.pipeline.steps import GenerationSteps


def test_slide_generation_prompt_uses_the_renderable_contract(settings, store):
    webinar = Webinar(
        id="web_slide_contract",
        theme="AI operations",
        audience="operators",
        duration_min=3,
        lang=Lang.EN,
        template=Template.TECH,
        style=Style.FORMAL,
        voice_id="voice",
    )
    steps = GenerationSteps(store=store, settings=settings)

    with patch.object(
        steps,
        "_call_json",
        return_value={"slides": [{"title": "A", "bullets": ["B"]}]},
    ) as call_json:
        result = steps.generate_slides(webinar, {"sections": [{"title": "A"}]})

    prompt = call_json.call_args.args[0][0]["content"]
    assert '"bullets"' in prompt
    assert '"visual"' in prompt
    assert '"items"' in prompt
    assert "placeholder-only media" in prompt
    assert result["slides"][0]["bullets"] == ["B"]
