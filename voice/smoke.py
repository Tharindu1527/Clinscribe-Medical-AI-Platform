"""Smoke test of the voice agent's answer step (Phase 4 gate): the agent's llm_node sends a spoken
question to the ClinScribe API and yields the cited answer as speech text. No microphone needed.

  uv run --project voice python voice/smoke.py      (needs `just up rag` and CLINSCRIBE_TOKEN)
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

from livekit.agents import llm

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
    context = llm.ChatContext()
    context.add_message(role="user", content="What is the usual starting dose of warfarin?")
    spoken = "".join([part async for part in agent.llm_node(context, [], None)])
    print(f"spoken: {spoken}\nturn: {agent.turns}")
    ok = "warfarin" in spoken.lower() and spoken.rstrip().endswith("Sources are on screen.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
