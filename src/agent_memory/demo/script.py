"""The scripted story for the fictional persona."""

PERSONA = "An"

PROMPTS = [
    "I'm An, I live in Ho Chi Minh City. Remind me to call the dentist on Friday.",
    "I just moved to Hanoi.",
    "Where do I live and what's on my list?",
]

SECOND_ACT = "This week I'm on a diet."

# Unverified placeholder until the real warm-up (T17) measures it: tokens per scripted turn, both columns together.
TOKENS_PER_TURN = 3000


def run_script(session, include_second_act: bool = False) -> None:
    for text in [*PROMPTS, *([SECOND_ACT] if include_second_act else [])]:
        session.turn(text)


def estimate_tokens(include_second_act: bool = False) -> int:
    return TOKENS_PER_TURN * (len(PROMPTS) + include_second_act)
