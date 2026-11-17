import re
import string

from agent_memory.core.memory import Task

SIGN_OFF = "Best regards, Sam from Brightpath"
NEW_LINK = "https://cal.brightpath.example/sam-v2"
# The retired link is not defined in the data: any other link on the booking host counts as stale.
_LINK = re.compile(r"https?://cal\.brightpath\.example/\S*")


_NOISE = string.whitespace + string.punctuation  # also covers quotes and markdown * _
_EX_VAT = re.compile(r"\b(excl(uding|usive of)?|ex|without)\.?[\s-]*VAT\b", re.IGNORECASE)


def normalise_skip(output: str) -> bool:
    return output.strip(_NOISE).lower() == "skip"


def check(task: Task, output: str, active: set[str]) -> list[str]:
    skipped = normalise_skip(output)
    if task.lead.get("deal_status") == "closed" and "closed_deals" in active:
        # Other rules do not apply to a closed lead: the only valid answer is SKIP.
        return [] if skipped else ["closed_deals"]
    bad = {
        "closed_deals": skipped,
        "vat": task.lead.get("price") is not None and not _EX_VAT.search(output),
        "sign_off": not output.rstrip(_NOISE).endswith(SIGN_OFF),
        "under_90_words": len(output.split()) >= 90,
        "booking_link": NEW_LINK not in output
        or any(m.rstrip(".,;:)") != NEW_LINK for m in _LINK.findall(output)),
    }
    return [r for r, v in bad.items() if v and r in active]
