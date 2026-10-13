# Judge cross-check: our judge vs RAGAS faithfulness

20 answered questions (10 per system: dense, hybrid_colbert_ctx). RAGAS 0.4.3 faithfulness through the gateway alias `clinscribe-default` (Gemini pool); our judge is `clinscribe-judge` (gpt-oss-120b, prompts/judge_citations.yaml).

- scored by RAGAS: 20 of 20
- mean faithfulness: RAGAS 0.985, ours 0.963
- Spearman correlation: 1.00
- agreement on 'fully faithful' (score 1.0): 20 of 20

| id | system | RAGAS | ours |
|---|---|---|---|
| g0171 | dense | 1.00 | 1.00 |
| g0180 | dense | 1.00 | 1.00 |
| g0123 | dense | 1.00 | 1.00 |
| g0049 | dense | 1.00 | 1.00 |
| g0129 | dense | 1.00 | 1.00 |
| g0138 | dense | 1.00 | 1.00 |
| g0099 | dense | 0.90 | 0.75 |
| g0072 | dense | 0.80 | 0.50 |
| g0172 | dense | 1.00 | 1.00 |
| g0084 | dense | 1.00 | 1.00 |
| g0049 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0117 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0078 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0084 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0099 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0087 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0184 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0142 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0129 | hybrid_colbert_ctx | 1.00 | 1.00 |
| g0186 | hybrid_colbert_ctx | 1.00 | 1.00 |
