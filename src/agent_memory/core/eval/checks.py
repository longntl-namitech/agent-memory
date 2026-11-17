import re

from agent_memory.core.memory import Task

SIGN_OFF = "Best regards, Sam from Brightpath"
NEW_LINK = "https://cal.brightpath.example/sam-v2"
# The retired link is not defined in the data: any other link on the booking host counts as stale.
_LINK = re.compile(r"https?://cal\.brightpath\.example/\S*")


def normalise_skip(output: str) -> bool:
    return output.strip().rstrip(".!?,;:").strip().lower() == "skip"


def check(task: Task, output: str, active: set[str]) -> list[str]:
    skipped = normalise_skip(output)
    if task.lead.get("deal_status") == "closed":
        # Other rules do not apply to a closed lead: the only valid answer is SKIP.
        return ["closed_deals"] if "closed_deals" in active and not skipped else []
    bad = {
        "closed_deals": skipped,
        "vat": task.lead.get("price") is not None and "VAT" not in output,
        "sign_off": SIGN_OFF not in output,
        "under_90_words": len(output.split()) >= 90,
        "booking_link": NEW_LINK not in output
        or any(m.rstrip(".,;:)") != NEW_LINK for m in _LINK.findall(output)),
    }
    return [r for r, v in bad.items() if v and r in active]
