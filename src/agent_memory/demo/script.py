"""The scripted story for the fictional persona."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_memory.demo.session import Session

PERSONA = "An"

PROMPTS = [
    "I'm An, I live in Ho Chi Minh City. Remind me to call the dentist on Friday.",
    "I just moved to Hanoi.",
    "Where do I live and what's on my list?",
]

SECOND_ACT = "This week I'm on a diet."

# Estimate, not a guarantee: the 2026-11-18 rehearsal (gpt-5.4-nano, text-embedding-3-small) used 3,631 tokens for
# 4 turns (about 900 per turn, both columns together); rounded up. Wording varies per run, so the cost does too.
TOKENS_PER_TURN = 1000


def run_script(session: "Session", include_second_act: bool = False) -> None:
    for text in [*PROMPTS, *([SECOND_ACT] if include_second_act else [])]:
        session.turn(text)


def estimate_tokens(include_second_act: bool = False) -> int:
    return TOKENS_PER_TURN * (len(PROMPTS) + include_second_act)
