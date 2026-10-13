import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from pydantic import SecretStr

from llmops.gateway.client import (
    CacheMissError,
    ChatMessage,
    GatewayClient,
    ReplayCache,
    alias_for,
)
from privacy.deid.types import DeidentifiedText, issue
from scripts.gateway_keys import ALIASES

GATEWAY_CONFIG = Path(__file__).resolve().parents[2] / "llmops" / "gateway" / "config.yaml"
HELLO = [ChatMessage("user", issue("Say hello.", source="synthetic-test-fixture"))]


def _fail_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call: {request.url}")

    return httpx.MockTransport(handler)


def _ok_transport(calls: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = {
            "id": "chatcmpl-1",
            "model": "groq/openai/gpt-oss-20b",
            "choices": [{"message": {"content": "Hello."}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 2},
        }
        return httpx.Response(200, json=body, headers={"x-litellm-call-id": "call-1"})

    return httpx.MockTransport(handler)


def _client(transport: httpx.MockTransport, cache: ReplayCache | None = None) -> GatewayClient:
    return GatewayClient("http://gateway", SecretStr("sk-test"), cache=cache, transport=transport)


def test_deidentified_text_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError):
        DeidentifiedText(text="John Smith, MRN 123", source="me")


def test_client_rejects_plain_str() -> None:
    raw: Any = "John Smith, MRN 123"  # Any: simulate a caller bypassing the type checker
    with pytest.raises(TypeError, match="DeidentifiedText"):
        _client(_fail_transport()).complete("clinscribe-default", [ChatMessage("user", raw)])


def test_completion_parsed_from_gateway_response() -> None:
    calls: list[httpx.Request] = []
    result = _client(_ok_transport(calls)).complete("clinscribe-default", HELLO)
    assert (result.text, result.model, result.call_id) == (
        "Hello.",
        "groq/openai/gpt-oss-20b",
        "call-1",
    )
    assert (result.input_tokens, result.output_tokens) == (9, 2)
    assert result.response_id == "chatcmpl-1"
    sent = json.loads(calls[0].content)
    assert sent["model"] == "clinscribe-default"
    assert calls[0].headers["Authorization"] == "Bearer sk-test"


def test_replay_cache_hit_makes_zero_network_calls(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    _client(_ok_transport(calls), ReplayCache(tmp_path, "record")).complete(
        "clinscribe-default", HELLO
    )
    assert len(calls) == 1

    replayed = _client(_fail_transport(), ReplayCache(tmp_path, "replay")).complete(
        "clinscribe-default", HELLO
    )
    assert replayed.cached
    assert replayed.text == "Hello."


def test_untraced_client_sends_no_log_without_changing_the_cache_key(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    traced = _client(_ok_transport(calls))
    traced.complete("clinscribe-default", HELLO)
    assert "no-log" not in json.loads(calls[0].content)

    untraced = GatewayClient(
        "http://gateway",
        SecretStr("sk-test"),
        cache=ReplayCache(tmp_path, "record"),
        transport=_ok_transport(calls),
        trace=False,
    )
    untraced.complete("clinscribe-default", HELLO)
    assert json.loads(calls[1].content)["no-log"] is True
    # a response recorded by an untraced client replays for a traced one (same key)
    replayed = _client(_fail_transport(), ReplayCache(tmp_path, "replay")).complete(
        "clinscribe-default", HELLO
    )
    assert replayed.cached


def test_collector_keeps_only_litellm_request_spans() -> None:
    collector = Path(__file__).resolve().parents[2] / "llmops" / "telemetry" / "collector.yaml"
    config = yaml.safe_load(collector.read_text(encoding="utf-8"))
    (condition,) = config["processors"]["filter/litellm_internal"]["traces"]["span"]
    assert 'instrumentation_scope.name == "litellm"' in condition
    for kept in ("litellm_request", "Received Proxy Server Request"):
        assert f'name != "{kept}"' in condition
    processors = config["service"]["pipelines"]["traces"]["processors"]
    assert processors.index("filter/litellm_internal") < processors.index("batch")


def test_replay_cache_miss_raises_without_network(tmp_path: Path) -> None:
    with pytest.raises(CacheMissError):
        _client(_fail_transport(), ReplayCache(tmp_path, "replay")).complete(
            "clinscribe-default", HELLO
        )


def test_task_alias_comes_from_models_yaml() -> None:
    assert alias_for("dev_complete") == "clinscribe-default"


def test_gateway_config_fallback_chain_matches_spec() -> None:
    config = yaml.safe_load(GATEWAY_CONFIG.read_text(encoding="utf-8"))
    deployments = config["model_list"]
    names = list(dict.fromkeys(m["model_name"] for m in deployments))  # aliases, in order
    provider_of = {
        name: {
            m["litellm_params"]["model"].split("/")[0]
            for m in deployments
            if m["model_name"] == name
        }
        for name in names
    }
    chain = config["router_settings"]["fallbacks"][0]["clinscribe-default"]

    # SPEC section 7 order: Gemini Flash -> Groq -> OpenRouter :free -> local Ollama
    # (aliases outside the chain, such as the evaluation judge, are not fallback targets)
    assert "clinscribe-judge" not in chain
    assert [provider_of[n] for n in ["clinscribe-default", *chain]] == [
        {"gemini"},
        {"groq"},
        {"openrouter"},
        {"ollama_chat"},
    ]
    assert "clinscribe-mock" not in chain  # load-test alias, never a fallback
    assert ["clinscribe-default", *chain] == [
        n for n in names if n not in ("clinscribe-judge", "clinscribe-mock")
    ]
    assert set(ALIASES) == set(names)  # the app key may use every alias (chain and judge)
    assert config["general_settings"]["store_prompts_in_spend_logs"] is False


def test_every_primary_deployment_obeys_the_chaos_switch() -> None:
    config = yaml.safe_load(GATEWAY_CONFIG.read_text(encoding="utf-8"))
    primary = [
        m["litellm_params"] for m in config["model_list"] if m["model_name"] == "clinscribe-default"
    ]
    assert len(primary) >= 2  # spread over several models: the free tier is 20 requests/day each
    assert all(p["api_base"] == "os.environ/GEMINI_API_BASE" for p in primary)
