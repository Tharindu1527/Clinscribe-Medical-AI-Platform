# Drill: primary provider outage

`chaos primary-down` on at 2026-10-13 19:52 UTC; 4 agentic Ask questions through the API; then off.

| question | status | seconds | route | abstained |
|---|---|---|---|---|
| Does clarithromycin interact with warfarin? | 200 | 5.1 | agentic | False |
| Apixaban versus warfarin for stroke prevention in atrial fibrillation? | 200 | 23.0 | agentic | False |
| Can a patient on metformin take contrast dye together with it? | 200 | 44.3 | agentic | False |
| Which is safer in pregnancy, labetalol or nifedipine? | 200 | 43.3 | agentic | False |

Gateway spend log for the window (alias <- deployment that served it):

| alias <- deployment | calls |
|---|---|
| clinscribe-fallback-groq <- groq/openai/gpt-oss-20b | 8 |
| clinscribe-fallback-local <- ollama_chat/llama3.2:3b | 2 |
