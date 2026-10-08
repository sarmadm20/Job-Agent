"""RevOps skills coach agent.

Each run:
  1. Researches what the RevOps job market currently rewards (live web search).
  2. Compares that against your profile.yaml and your logged progress.
  3. Writes a prioritized skill-gap report to reports/YYYY-MM-DD.md.

Usage:
  python agent.py report                 # generate a new report
  python agent.py log "built a lead-scoring model in HubSpot"   # record practice
"""

import argparse
import datetime as dt
import json
import pathlib
import sys

import anthropic
import yaml

ROOT = pathlib.Path(__file__).parent
PROFILE = ROOT / "profile.yaml"
REPORTS = ROOT / "reports"
HISTORY = ROOT / "data" / "history.json"

MODEL = "claude-opus-5-5"
BETAS = ["server-side-fallback-2026-07-01"]

RESEARCH_SYSTEM = """You are a career researcher specializing in Revenue Operations (RevOps).
Search the web for CURRENT evidence (prefer the last 6 months) about what employers pay for in RevOps.
Look at: real job postings for the person's target roles, salary data, HubSpot and Apollo product
releases and certifications, and RevOps community discussion about where the field is heading
(e.g. AI agents, data enrichment, GTM engineering).
Write concise research notes. Every claim should name its source. Note how often each skill shows
up in postings and whether it is tied to higher pay. Flag skills that are declining in value too."""

COACH_SYSTEM = """You are a blunt, encouraging RevOps career coach. You turn market research and a
self-assessment into a short, prioritized plan. Rules:
- Rank skills by (market demand x pay impact x gap size). Ignore skills the person is already strong in.
- Be specific to HubSpot and Apollo where possible: name the exact feature, cert, or project.
- Every skill needs one hands-on project they can do at work in under two weeks.
- Explain the "why" in plain English a teenager would follow, using an analogy where it helps.
- Challenge the person: if their self-rating looks inflated, their target role is mismatched with
  their skills, or they are avoiding a high-value skill, say so in `challenges`.
- Compare with the previous report (if given) and say what changed and whether they made progress."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One plain-English sentence summary."},
        "market_pulse": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-6 bullet takeaways from the research, each with its source.",
        },
        "priority_skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "current_level": {"type": "integer"},
                    "target_level": {"type": "integer"},
                    "why_it_matters": {"type": "string"},
                    "analogy": {"type": "string"},
                    "project": {"type": "string"},
                    "resources": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "skill", "current_level", "target_level", "why_it_matters",
                    "analogy", "project", "resources",
                ],
                "additionalProperties": False,
            },
        },
        "this_week": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 concrete actions for the next 7 days.",
        },
        "progress_since_last": {"type": "string"},
        "challenges": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Honest pushback or questions for the person.",
        },
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "meaning": {"type": "string"}},
                "required": ["term", "meaning"],
                "additionalProperties": False,
            },
            "description": "Define every acronym or jargon term used above.",
        },
    },
    "required": [
        "headline", "market_pulse", "priority_skills", "this_week",
        "progress_since_last", "challenges", "glossary",
    ],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- storage

def load_history() -> dict:
    if HISTORY.exists():
        return json.loads(HISTORY.read_text())
    return {"logs": [], "reports": []}


def save_history(history: dict) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(history, indent=2) + "\n")


# ---------------------------------------------------------------- model calls

def check_refusal(response) -> None:
    if response.stop_reason == "refusal":
        sys.exit(f"Model declined the request: {response.stop_details}")


def research(client: anthropic.Anthropic, profile: dict) -> str:
    """Phase 1: live web research on what the market wants right now."""
    prompt = (
        f"Today is {dt.date.today().isoformat()}. Research the current market for this person:\n\n"
        f"{yaml.safe_dump(profile, sort_keys=False)}"
    )
    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 12}]

    for _ in range(5):  # resume if the server-side search loop pauses
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=RESEARCH_SYSTEM,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            betas=BETAS,
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
        check_refusal(response)
        if response.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": response.content}]

    return "\n".join(b.text for b in response.content if b.type == "text")


def coach(client: anthropic.Anthropic, profile: dict, notes: str, history: dict) -> dict:
    """Phase 2: turn research + profile + history into a structured plan."""
    last_report = history["reports"][-1] if history["reports"] else None
    since = last_report["date"] if last_report else ""
    recent_logs = [log for log in history["logs"] if log["date"] >= since]

    prompt = (
        f"## Profile\n{yaml.safe_dump(profile, sort_keys=False)}\n"
        f"## Market research (gathered today)\n{notes}\n\n"
        f"## Practice the person logged since the last report\n"
        f"{json.dumps(recent_logs, indent=2) if recent_logs else 'Nothing logged.'}\n\n"
        f"## Previous report\n"
        f"{json.dumps(last_report['plan'], indent=2) if last_report else 'This is the first report.'}\n\n"
        "Build this period's plan. Pick the top 3-5 priority skills."
    )
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=COACH_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        betas=BETAS,
        fallbacks="default",
    ) as stream:
        response = stream.get_final_message()
    check_refusal(response)
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# ---------------------------------------------------------------- rendering

def render_markdown(plan: dict, date: str) -> str:
    out = [f"# RevOps skills update — {date}", "", f"**{plan['headline']}**", ""]

    out += ["## What the market wants right now", ""]
    out += [f"- {item}" for item in plan["market_pulse"]] + [""]

    out += ["## Skills to level up (in priority order)", ""]
    for i, s in enumerate(plan["priority_skills"], 1):
        out += [
            f"### {i}. {s['skill']}  ({s['current_level']} → {s['target_level']})",
            "",
            f"**Why it matters:** {s['why_it_matters']}",
            "",
            f"**Think of it like:** {s['analogy']}",
            "",
            f"**Prove it with a project:** {s['project']}",
            "",
            "**Resources:**",
            *[f"- {r}" for r in s["resources"]],
            "",
        ]

    out += ["## Do this week", ""]
    out += [f"- [ ] {a}" for a in plan["this_week"]] + [""]

    out += ["## Progress since last report", "", plan["progress_since_last"], ""]

    out += ["## Pushback from your coach", ""]
    out += [f"- {c}" for c in plan["challenges"]] + [""]

    out += ["## Glossary", ""]
    out += [f"- **{g['term']}** — {g['meaning']}" for g in plan["glossary"]] + [""]
    return "\n".join(out)


# ---------------------------------------------------------------- commands

def cmd_report(_args) -> None:
    profile = yaml.safe_load(PROFILE.read_text())
    history = load_history()
    client = anthropic.Anthropic()

    print("Researching the RevOps job market…", file=sys.stderr)
    notes = research(client, profile)
    print("Building your plan…", file=sys.stderr)
    plan = coach(client, profile, notes, history)

    date = dt.date.today().isoformat()
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{date}.md"
    markdown = render_markdown(plan, date)
    path.write_text(markdown)
    (REPORTS / f"{date}-research.md").write_text(f"# Raw research notes — {date}\n\n{notes}\n")

    history["reports"].append({"date": date, "plan": plan})
    save_history(history)
    print(markdown)
    print(f"\nSaved to {path}", file=sys.stderr)


def cmd_log(args) -> None:
    history = load_history()
    history["logs"].append({"date": dt.date.today().isoformat(), "note": args.note})
    save_history(history)
    print(f"Logged. {len(history['logs'])} entries total.")


def main() -> None:
    parser = argparse.ArgumentParser(description="RevOps skills coach agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("report", help="research the market and write a new skills report")
    log = sub.add_parser("log", help="record something you practiced or shipped")
    log.add_argument("note")
    args = parser.parse_args()
    {"report": cmd_report, "log": cmd_log}[args.command](args)


if __name__ == "__main__":
    main()
