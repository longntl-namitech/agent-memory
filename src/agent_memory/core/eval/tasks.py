"""Seeded task stream for the email follow-up simulation (ids 0-39, 10 per week)."""
import json
import random
from dataclasses import asdict
from pathlib import Path

from agent_memory.core.memory import Task

COMPANIES = [
    "Acme Corp", "Bluefin Logistics", "Cedar Dental", "Delta Print", "Eastside Bakery",
    "Fjord Analytics", "Greenleaf Farms", "Harbor Legal", "Ironwood Joinery", "Juniper Studio",
    "Kite Travel", "Lumen Optics", "Maple Fitness", "Northwind Tools", "Orchid Spa",
    "Pinecone Books", "Quartz Labs", "Redwood Cafe", "Summit Rentals", "Tidal Marine",
]
FIRST = ["Ana", "Ben", "Chloe", "Dev", "Elena", "Farid", "Grace", "Hugo", "Iris", "Jon"]
PRODUCTS = ["website audit", "monthly SEO plan", "logo refresh", "ad campaign setup", "CRM migration"]
PRICES = [490, 750, 1200, 1800, 2400, 3200]
DEAL_STATUS = ["open", "open", "open", "negotiating", "closed"]
TASKS_PER_WEEK = 10


def slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def generate(seed: int = 7) -> list[Task]:
    rng = random.Random(seed)
    tasks = []
    for i in range(4 * TASKS_PER_WEEK):
        company = COMPANIES[i % len(COMPANIES)] if i < len(COMPANIES) else rng.choice(COMPANIES)
        lead = {
            "name": rng.choice(FIRST),
            "company": company,
            "product": rng.choice(PRODUCTS),
            "price": rng.choice(PRICES),
            "deal_status": rng.choice(DEAL_STATUS),
            "last_contact_days": rng.randint(2, 21),
        }
        tasks.append(Task(
            id=i,
            week=i // TASKS_PER_WEEK + 1,
            day=i % TASKS_PER_WEEK // 2 + 1,  # two tasks per weekday, Mon=1
            lead=lead,
            tags=[slug(company)],
            wants_log=rng.random() < 0.25,
        ))
    return tasks


def write_jsonl(tasks: list[Task], path: Path) -> None:
    lines = [json.dumps(asdict(t), sort_keys=True) for t in tasks]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    write_jsonl(generate(), Path(__file__).resolve().parents[4] / "data" / "simulation" / "tasks.jsonl")
