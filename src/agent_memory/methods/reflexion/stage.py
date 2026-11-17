import json
import re

from agent_memory.core.eval.checks import rule_wording
from agent_memory.core.llm import LLMClient
from agent_memory.core.memory import RetryResult, RetryStage, Task
from agent_memory.core.registry import register

_PROMPT = """Your output for this task failed a check. The rule that failed is: {check}
Reflect briefly on what went wrong and what to do next time, then write the corrected output.
If the rule says to skip, the output must be exactly SKIP.
Reply with JSON only: {{"note": str, "output": str}}
- note: a short reflection (what went wrong, what to do next time).
- output: the corrected output.
Lead: {lead}
Your first output:
{first}
Memory you had:
{context}"""


@register("reflexion", "retry")
class Reflexion(RetryStage):
    """One LLM call: told which check failed, returns a reflection note and a corrected output."""

    def __init__(self) -> None:
        self.fallbacks = 0  # replies that were not usable JSON, taken as the output with no note

    def retry(self, task: Task, first_output: str, failed_check: str, context: str, llm: LLMClient) -> RetryResult:
        prompt = _PROMPT.format(check=f"{failed_check}: {rule_wording(failed_check)}", lead=json.dumps(task.lead, ensure_ascii=False),
                                first=first_output, context=context)
        reply = llm.chat([{"role": "user", "content": prompt}], purpose="reflexion").text
        d = self._parse(reply)
        if d is None:
            self.fallbacks += 1
            return RetryResult(reply, "")
        return RetryResult(d["output"], d["note"])

    @staticmethod
    def _parse(reply: str) -> dict | None:
        m = re.search(r"\{.*\}", reply, re.S)  # tolerate a code fence or prose around the JSON
        try:
            d = json.loads(m.group(0)) if m else None
            out = str(d["output"]).strip()
            return {"output": out, "note": str(d.get("note") or "").strip()} if out else None
        except (TypeError, KeyError, ValueError, AttributeError):
            return None
