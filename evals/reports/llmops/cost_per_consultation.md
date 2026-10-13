# Cost per consultation, by model choice

One consultation = 1 Scribe draft + 3 Ask questions: ~8,153 input and ~4,183 output tokens (method in `evals/llmops/cost_report.py`). List prices;
the free tiers used in this build bill $0.

| model | draft USD | 3 questions USD | consultation USD | per 1,000 consultations |
|---|---|---|---|---|
| gemini/gemini-3.5-flash | 0.0342 | 0.0157 | 0.0499 | 49.88 |
| gemini/gemini-3.6-flash | 0.0146 | 0.0072 | 0.0218 | 21.80 |
| gemini/gemini-2.5-flash | 0.0092 | 0.0038 | 0.0129 | 12.90 |
| gemini/gemini-3.5-flash-lite | 0.0092 | 0.0038 | 0.0129 | 12.90 |
| groq/openai/gpt-oss-120b | 0.0024 | 0.0013 | 0.0037 | 3.73 |
| groq/openai/gpt-oss-20b | 0.0012 | 0.0007 | 0.0019 | 1.87 |
| ollama_chat/llama3.2:3b (local) | 0.0000 | 0.0000 | 0.0000 | 0.00 |

The local model costs no API fee but is slow on the 4 GB laptop GPU (23-44 s per
question during the outage drill) and too small for long notes: a last resort.
Output tokens dominate (reasoning counts as output), so the thinking level per task
is the main cost lever after the model itself.
