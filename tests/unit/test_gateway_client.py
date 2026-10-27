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


def test_provider_prompt_cache_hits_are_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        usage = {"prompt_tokens": 2400, "completion_tokens": 5,
                 "prompt_tokens_details": {"cached_tokens": 2048}}  # fmt: skip
        body = {"id": "c", "model": "m", "choices": [{"message": {"content": "x"}}]}
        return httpx.Response(200, json={**body, "usage": usage})

    reply = _client(httpx.MockTransport(handler)).complete("clinscribe-default", HELLO)
    assert reply.cached_input_tokens == 2048
    no_details = _client(_ok_transport([])).complete("clinscribe-default", HELLO)
    assert no_details.cached_input_tokens == 0


def test_gateway_retries_are_reported() -> None:
    # LiteLLM retries a rate-limited call itself (num_retries), and the wait lands in the
    # latency; a timing run must be able to see it (ADR-0025)
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"model": "m", "choices": [{"message": {"content": "ok"}}], "usage": {}}
        return httpx.Response(200, json=body, headers={"x-litellm-attempted-retries": "1"})

    assert _client(httpx.MockTransport(handler)).complete("m", HELLO).retries == 1
    assert _client(_ok_transport([])).complete("m", HELLO).retries == 0


def test_reasoning_effort_is_sent_only_when_asked() -> None:
    calls: list[httpx.Request] = []
    client = _client(_ok_transport(calls))
    client.complete("clinscribe-judge", HELLO)
    client.complete("clinscribe-judge", HELLO, reasoning_effort="low")
    assert "reasoning_effort" not in json.loads(calls[0].content)  # old cache keys unchanged
    assert json.loads(calls[1].content)["reasoning_effort"] == "low"


def test_fallbacks_can_be_turned_off_without_changing_the_cache_key(tmp_path: Path) -> None:
    # an evaluation of one model asks LiteLLM not to fail over (ADR-0025): a fallback had
    # silently answered timing calls with the local model
    calls: list[httpx.Request] = []
    client = _client(_ok_transport(calls), ReplayCache(tmp_path, "record"))
    client.complete("clinscribe-fallback-groq", HELLO)
    assert "disable_fallbacks" not in json.loads(calls[0].content)
    pinned = _client(_ok_transport(calls))
    pinned.complete("clinscribe-fallback-groq", HELLO, fallbacks=False)
    assert json.loads(calls[1].content)["disable_fallbacks"] is True
    replayed = _client(_fail_transport(), ReplayCache(tmp_path, "replay")).complete(
        "clinscribe-fallback-groq", HELLO, fallbacks=False
    )
    assert replayed.cached  # same key as the request with fallbacks


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


def test_fallback_targets_that_cannot_reason_drop_reasoning_effort() -> None:
    # ADR-0025: the cited answer sets reasoning_effort for gpt-oss; LiteLLM's drop_params keeps
    # it for Ollama (as "think") and llama3.2 refused the request, so the last fallback failed
    config = yaml.safe_load(GATEWAY_CONFIG.read_text(encoding="utf-8"))
    params = {m["model_name"]: m["litellm_params"] for m in config["model_list"]}
    targets = {
        t for chain in config["router_settings"]["fallbacks"] for ts in chain.values() for t in ts
    }
    for alias in targets:
        if "gpt-oss" not in params[alias]["model"]:
            assert "reasoning_effort" in params[alias].get("additional_drop_params", []), alias
    assert config["litellm_settings"]["drop_params"] is True


def test_every_primary_deployment_obeys_the_chaos_switch() -> None:
    config = yaml.safe_load(GATEWAY_CONFIG.read_text(encoding="utf-8"))
    primary = [
        m["litellm_params"] for m in config["model_list"] if m["model_name"] == "clinscribe-default"
    ]
    assert len(primary) >= 2  # spread over several models: the free tier is 20 requests/day each
    assert all(p["api_base"] == "os.environ/GEMINI_API_BASE" for p in primary)
