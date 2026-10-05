# Gateway latency: primary up vs down

20 calls per mode to `clinscribe-default`, max_tokens 256, paced 3 s apart.
Client-side wall time through the LiteLLM gateway (free tiers; network to providers included).

| Mode | Succeeded | p50 ms | p95 ms | Served by |
|---|---|---|---|---|
| primary up | 20/20 | 2,564 | 3,821 | clinscribe-default x19, openai/gpt-oss-20b x1 |
| primary down | 20/20 | 779 | 1,080 | openai/gpt-oss-20b x20 |

Every turn succeeded in both modes: **PASS**
