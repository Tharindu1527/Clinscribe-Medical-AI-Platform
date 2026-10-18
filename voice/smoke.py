"""Smoke test of the voice agent's answer step (Phase 4 gate): a question goes through a LiveKit
AgentSession (text input, so no microphone) to the agent's llm_node, which asks the ClinScribe API
and returns the cited answer as speech text. Running it through the session, not llm_node alone,
catches LiveKit skipping the reply (it does when the session has no LLM).

  uv run --project voice python voice/smoke.py      (needs `just up rag` and CLINSCRIBE_TOKEN)
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

from livekit.agents import AgentSession

spec = importlib.util.spec_from_file_location(
    "agent", Path(__file__).with_name("agent_cascaded.py")
)
if spec is None or spec.loader is None:
    raise ImportError("voice/agent_cascaded.py not found")
agent_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_module)


async def main() -> int:
    agent_module.load_env()
    agent = agent_module.ClinScribeVoice()
    async with AgentSession(llm=agent_module.AskApi()) as session:
        await session.start(agent)
        result = await session.run(user_input="What is the usual starting dose of warfarin?")
    spoken = " ".join(
        event.item.text_content or "" for event in result.events if event.type == "message"
    )
    print(f"spoken: {spoken}\nturn: {agent.turns}")
    ok = "warfarin" in spoken.lower() and spoken.rstrip().endswith("Sources are on screen.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
