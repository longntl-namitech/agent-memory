from agent_memory.core.eval.checks import check, normalise_skip
from agent_memory.core.memory import Task

SIGN = "Best regards, Sam from Brightpath"
NEW = "https://cal.brightpath.example/sam-v2"
ALL = {"vat", "sign_off", "closed_deals", "under_90_words", "booking_link"}


def task(status="open", price=1200):
    lead = {"company": "Acme", "deal_status": status, "price": price}
    return Task(id=25, week=3, day=1, lead=lead, tags=[], wants_log=False)


def good(extra=""):
    return f"Hi, 1,200 USD excl. VAT. Book {NEW} {extra}\n{SIGN}"


def test_word_limit():
    pad = lambda n: " ".join(["w"] * n)
    base = len(good().split())
    assert "under_90_words" not in check(task(), good(pad(89 - base)), ALL)
    assert "under_90_words" in check(task(), good(pad(90 - base)), ALL)


def test_vat_mentioned():
    assert check(task(), good(), ALL) == []
    assert check(task(), good().replace("VAT", "tax"), ALL) == ["vat"]


def test_signoff_string():
    assert check(task(), good().replace(SIGN, "Best regards, Sam"), ALL) == ["sign_off"]


def test_stale_booking_link_flagged_after_task_20():
    stale = good().replace(NEW, "https://cal.brightpath.example/sam")
    assert check(task(), stale, ALL) == ["booking_link"]
    assert check(task(), stale, ALL - {"booking_link"}) == []
    assert check(task(), good().replace(NEW, ""), ALL) == ["booking_link"]


def test_skip_variants():
    assert all(normalise_skip(s) for s in ["SKIP", "skip.", " SKIP "])
    assert not normalise_skip("Skipping this")


def test_only_active_rules_checked():
    assert check(task(), "nothing", set()) == []
    assert check(task(), "nothing", {"sign_off"}) == ["sign_off"]
    assert check(task("closed"), "SKIP", ALL) == []
    assert check(task("closed"), good(), ALL) == ["closed_deals"]
    assert "closed_deals" in check(task(), "skip.", ALL)


def test_vat_must_be_excluding():
    for ok in ["excl. VAT", "Excl VAT", "exclusive of VAT", "without VAT"]:
        assert check(task(), good().replace("excl. VAT", ok), ALL) == [], ok
    for bad in ["incl. VAT", "plus 20% VAT", "VAT"]:
        assert check(task(), good().replace("excl. VAT", bad), ALL) == ["vat"], bad


def test_signoff_must_end_email():
    assert check(task(), good() + " **\n", ALL) == []
    assert check(task(), good() + ".", ALL) == []
    assert check(task(), good() + "\nCall me soon", ALL) == ["sign_off"]
    assert check(task(), good() + "\nP.S. call me", ALL) == ["sign_off"]


def test_closed_lead_rules_when_closed_deals_inactive():
    t7 = Task(id=7, week=1, day=4, lead={"deal_status": "closed", "price": 1}, tags=[], wants_log=False)
    out = f"Hi. Book {NEW}\n{SIGN}"
    assert check(t7, out, {"vat"}) == ["vat"]


def test_skip_markdown_and_quotes():
    assert normalise_skip("**SKIP**") and normalise_skip('"SKIP"')
    assert not normalise_skip("SKIP - closed")
