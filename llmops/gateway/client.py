"""The only way app code calls an LLM: through the LiteLLM proxy (ADR-0001).

- Message content must be `DeidentifiedText` (checked statically and at runtime).
- The caller names a gateway alias (see config/models.yaml); the proxy handles failover.
- `ReplayCache` records responses for tests, so test runs do not spend free-tier quota.
"""

import hashlib
import json
import os
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx
import yaml
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind
from pydantic import SecretStr

from privacy.deid.types import DeidentifiedText

_tracer = trace.get_tracer("clinscribe.gateway")
Role = Literal["system", "user", "assistant"]
CacheMode = Literal["off", "record", "replay"]
MODELS_FILE = Path(__file__).resolve().parents[2] / "config" / "models.yaml"


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: DeidentifiedText


@dataclass(frozen=True)
class Completion:
    text: str
    model: (
        str  # as reported by the gateway: the real deployment after failover, else may be the alias
    )
    input_tokens: int
    output_tokens: int
    latency_ms: float
    response_id: str | None = None  # LiteLLM spend logs record the call under this id
    call_id: str | None = None
    cached: bool = False  # replayed from the local cache (not a provider cache)
    cached_input_tokens: int = 0  # input tokens the provider served from its prompt cache


class CacheMissError(LookupError):
    """Replay mode found no recorded response for this request."""


class ReplayCache:
    """Stores completions as JSON files keyed by a hash of the request.

    replay: return a recorded response or raise CacheMissError (never touches the network)
    record: return a recorded response, otherwise call the gateway and record the answer
    off:    always call the gateway
    Only de-identified, synthetic text is ever written here.
    """

    def __init__(self, directory: Path, mode: CacheMode) -> None:
        self.directory = directory
        self.mode = mode

    @staticmethod
    def key(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get(self, key: str) -> Completion | None:
        path = self.directory / f"{key}.json"
        if self.mode == "off" or not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Completion(**{**data, "cached": True})

    def put(self, key: str, completion: Completion) -> None:
        if self.mode != "record":
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {**asdict(completion), "cached": False}
        (self.directory / f"{key}.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def alias_for(task: str, models_file: Path = MODELS_FILE) -> str:
    """The gateway alias configured for a task in config/models.yaml, unless
    CLINSCRIBE_MODEL_OVERRIDE is set (load tests point every task at `clinscribe-mock`)."""
    override = os.environ.get("CLINSCRIBE_MODEL_OVERRIDE")
    if override:
        return override
    config = yaml.safe_load(models_file.read_text(encoding="utf-8"))
    return str(config["tasks"][task])


class GatewayClient:
    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        *,
        cache: ReplayCache | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120.0,
        trace: bool = True,
    ) -> None:
        # trace=False (eval and batch jobs) asks LiteLLM to skip its logging callbacks ("no-log"),
        # so bulk calls do not use up the tracing backend's quota; spend logs still record them
        self._trace = trace
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            transport=transport,
            timeout=timeout,
        )
        self._cache = cache

    def close(self) -> None:
        self._http.close()

    def complete(
        self,
        model: str,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
        response_format: dict[str, object] | None = None,
        reasoning_effort: str | None = None,
    ) -> Completion:
        for message in messages:
            if not isinstance(message.content, DeidentifiedText):
                raise TypeError(
                    "LLM input must be DeidentifiedText (pass text through privacy/deid)"
                )

        payload: dict[str, object] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content.text} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:  # e.g. {"type": "json_object"}; absent keeps old cache keys
            payload["response_format"] = response_format
        if reasoning_effort is not None:  # gpt-oss: low/medium/high; absent keeps old keys
            payload["reasoning_effort"] = reasoning_effort
        key = ReplayCache.key(payload)
        # GenAI semantic conventions; message content is never put on the span
        with _tracer.start_as_current_span(f"chat {model}", kind=SpanKind.CLIENT) as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("gen_ai.request.max_tokens", max_tokens)
            span.set_attribute("gen_ai.request.temperature", temperature)
            if self._cache is not None:
                hit = self._cache.get(key)
                span.set_attribute("clinscribe.cache_hit", hit is not None)
                if hit is not None:
                    return hit
                if self._cache.mode == "replay":
                    raise CacheMissError(f"no recorded response for request {key[:12]}")

            headers: dict[str, str] = {}
            propagate.inject(headers)  # the gateway's spans join this trace
            started = time.perf_counter()
            body_out = payload if self._trace else {**payload, "no-log": True}  # not in the key
            response = self._http.post("/v1/chat/completions", json=body_out, headers=headers)
            latency_ms = (time.perf_counter() - started) * 1000
            span.set_attribute("http.response.status_code", response.status_code)
            response.raise_for_status()
            body = response.json()
            usage = body.get("usage") or {}
            completion = Completion(
                text=body["choices"][0]["message"].get("content") or "",
                model=str(body.get("model", "")),
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                latency_ms=round(latency_ms, 1),
                response_id=body.get("id"),
                call_id=response.headers.get("x-litellm-call-id"),
                cached_input_tokens=int(
                    (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                ),
            )
            span.set_attribute("gen_ai.response.model", completion.model)
            span.set_attribute("gen_ai.response.id", completion.response_id or "")
            span.set_attribute("gen_ai.usage.input_tokens", completion.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", completion.output_tokens)
        if self._cache is not None:
            self._cache.put(key, completion)
        return completion
