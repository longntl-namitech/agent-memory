"""Run HermesAgent on one task against the test stub (no real Hermes, no LLM, no network).

    uv run python -m agent_memory.methods.hermes.example [path/to/hermes]
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

from agent_memory.core.memory import Task
from agent_memory.methods.hermes.adapter import HermesAgent

STUB = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "fake_hermes.sh"

if __name__ == "__main__":
    binary = sys.argv[1] if len(sys.argv) > 1 else str(STUB)
    now = datetime(2026, 1, 5, 9)
    task = Task(0, 1, 1, {"name": "Ann", "company": "Acme", "product": "alpha", "price": 1200}, ["acme"], False)
    with tempfile.TemporaryDirectory() as home, HermesAgent(Path(home), "gpt-5.4-nano", True, binary) as agent:
        agent.plant_rule("Never mention prices in follow-up emails.")
        agent.receive_correction("Quote prices excl. VAT.", now)
        result = agent.run_task(task, now)
        print("version:", agent.version())
        print("output:", result.output, "| tokens:", result.tokens, "| failed:", result.failed_check)
        print("removed by review:", agent.review(["never mention prices"]), "| MEMORY.md size:", agent.memory_size())
