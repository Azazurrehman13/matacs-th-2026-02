"""
Proposal triage prototype.

AI does ONE job: extract structured facts from proposal text (live mode).
Everything else (mandatory checks, flags, scoring, ranking) is plain code.

Usage:
  python ranker.py --offline                 # score from fixtures/extracted_fixtures.json (no API key needed)
  python ranker.py --live                    # extract with Claude from samples/A.txt ... E.txt (kept local, git-ignored)
"""
import argparse, hashlib, json, os, re, sys, datetime
from pathlib import Path

HERE = Path(__file__).parent
CRITERIA = json.loads((HERE / "criteria.json").read_text(encoding="utf-8"))
OUT = HERE / "out"

# ---------- extraction (AI) ----------

EXTRACTION_TOOL = {
    "name": "record_extraction",
    "description": "Record facts extracted from the proposal. Use null when not stated.",
    "input_schema": {
        "type": "object",
        "properties": {
            "licence_held_by_bidder": {"type": ["boolean", "null"]},
            "licence_number": {"type": ["string", "null"]},
            "wsib_confirmed": {"type": ["boolean", "null"]},
            "insurance_5m_confirmed": {"type": ["boolean", "null"]},
            "qualifying_installs_5y": {"type": ["integer", "null"]},
            "experience_window_ambiguous": {"type": "boolean"},
            "price_cad": {"type": ["number", "null"]},
            "weeks": {"type": ["number", "null"]},
            "panel_warranty_years": {"type": ["number", "null"]},
            "workmanship_warranty_years": {"type": ["number", "null"]},
            "named_project_lead": {"type": "boolean"},
            "crew_stated": {"type": "boolean"},
            "safety_plan": {"type": "boolean"},
            "monitoring_plan": {"type": "boolean"},
            "reviewer_instructions_detected": {"type": "boolean"},
            "evidence": {"type": "object", "description": "field name -> exact quote from the proposal"},
        },
        "required": ["licence_held_by_bidder", "wsib_confirmed", "insurance_5m_confirmed",
                     "qualifying_installs_5y", "price_cad", "weeks", "panel_warranty_years",
                     "workmanship_warranty_years", "named_project_lead", "crew_stated",
                     "safety_plan", "monitoring_plan", "reviewer_instructions_detected", "evidence"],
    },
}


def load_system_prompt():
    text = (HERE.parent / "PROMPTS.md").read_text(encoding="utf-8")
    m = re.search(r"## Extraction prompt.*?```text\n(.*?)```", text, re.S)
    if not m:
        sys.exit("Could not find the extraction prompt block in PROMPTS.md")
    return m.group(1).strip()


def extract_live(text, system_prompt):
    import anthropic
    from dotenv import load_dotenv
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is missing. Copy .env.example to .env and add your key (or use --offline).")
    client = anthropic.Anthropic()
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    kwargs = dict(
        model=model, max_tokens=1500, system=system_prompt,
        tools=[EXTRACTION_TOOL], tool_choice={"type": "tool", "name": "record_extraction"},
        messages=[{"role": "user", "content": f"<proposal>\n{text}\n</proposal>"}],
    )
    try:
        resp = client.messages.create(temperature=0, **kwargs)
    except TypeError:
        # This SDK version does not accept a temperature argument; retry without it.
        resp = client.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        # Some models do not accept a temperature setting; retry without it.
        if "temperature" in str(e).lower():
            resp = client.messages.create(**kwargs)
        else:
            raise
    data = next(b.input for b in resp.content if b.type == "tool_use")
    return data, model


# Rule-based safety net: catches injection even if the model misses it.
INJECTION_PATTERNS = re.compile(
    r"(automated review|ai system|ignore (all|previous)|rank (it|this) first|full marks|pre-?approved)", re.I)


def _norm(t):
    return re.sub(r"\s+", " ", t).strip()


def verify_evidence(data, text):
    """Every quote the model gives must literally appear in the source (ignoring line breaks/extra spaces)."""
    src = _norm(text)
    return [k for k, q in (data.get("evidence") or {}).items() if q and _norm(q) not in src]


# ---------- rules: checks, flags, scoring ----------

def mandatory_check(x):
    """Returns (status, reasons). status: pass | fail | unclear"""
    reasons, status = [], "pass"
    lic = x.get("licence_held_by_bidder")
    if lic is False:
        status, _ = "fail", reasons.append("Licence not held by the bidder (subcontracted or absent)")
    elif lic is None:
        status = "unclear" if status != "fail" else status
        reasons.append("Licence not clearly stated")
    for key, label in (("wsib_confirmed", "WSIB clearance"), ("insurance_5m_confirmed", "$5M liability insurance")):
        v = x.get(key)
        if v is False:
            status = "fail"; reasons.append(f"{label} not confirmed")
        elif v is None and status != "fail":
            status = "unclear"; reasons.append(f"{label} unclear")
    return status, reasons


def flags_for(x, c):
    f = []
    if x.get("reviewer_instructions_detected"):
        f.append("Contains instructions aimed at automated reviewers (ignored; needs human review)")
    if x.get("weeks") is None:
        f.append("No completion time stated; timeline cannot be scored")
    elif x["weeks"] > c["max_weeks"]:
        f.append("Completion time exceeds 16-week limit")
    if x.get("price_cad") is None:
        f.append("No price stated")
    elif x["price_cad"] > c["budget_ceiling_cad"]:
        f.append("Price above budget ceiling")
    if x.get("experience_window_ambiguous"):
        f.append("Experience window may exceed 5 years; reviewer to confirm count")
    return f


def clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def score(x, c, lowest_price):
    s, w = c["scoring"], c["weights"]
    sub = {}
    n = x.get("qualifying_installs_5y") or 0
    sub["experience"] = clamp(n / s["experience"]["full_marks_at_installs"] * 100)
    p = x.get("price_cad")
    sub["price"] = clamp(lowest_price / p * 100) if p else 0
    wk = x.get("weeks")
    if wk is None:
        sub["timeline"] = 0
    else:
        top = s["timeline"]["full_marks_at_weeks"]
        sub["timeline"] = clamp((c["max_weeks"] - wk) / (c["max_weeks"] - top) * 100)
    wr = s["warranty"]
    panel = clamp((x.get("panel_warranty_years") or 0) / wr["panel_full_years"] * 100)
    work = clamp((x.get("workmanship_warranty_years") or 0) / wr["workmanship_full_years"] * 100)
    sub["warranty"] = panel * wr["panel_share"] + work * (1 - wr["panel_share"])
    items = ["named_project_lead", "crew_stated", "safety_plan", "monitoring_plan"]
    sub["team"] = sum(25 for i in items if x.get(i))
    total = sum(sub[k] * w[k] / 100 for k in w)
    return round(total, 1), {k: round(v, 1) for k, v in sub.items()}


def run(extractions):
    c = CRITERIA
    results = {}
    for pid, x in extractions.items():
        m_status, m_reasons = mandatory_check(x)
        results[pid] = {"x": x, "mandatory": m_status, "mandatory_reasons": m_reasons, "flags": flags_for(x, c)}
    # price is scored relative to the lowest bid among proposals that passed mandatory checks
    priced = [r["x"]["price_cad"] for r in results.values() if r["mandatory"] != "fail" and r["x"].get("price_cad")]
    lowest = min(priced) if priced else 1
    out = []
    for pid, r in results.items():
        if r["mandatory"] == "fail":
            out.append({"proposal": pid, "rank": None, "status": "ineligible", "score": None,
                        "reason": "; ".join(r["mandatory_reasons"]), "breakdown": None})
            continue
        total, sub = score(r["x"], c, lowest)
        status = "flagged" if (r["flags"] and any("Experience window" not in f for f in r["flags"])) \
                 or r["mandatory"] == "unclear" else "ranked"
        out.append({"proposal": pid, "rank": None, "status": status, "score": total,
                    "reason": "", "breakdown": sub, "flags": r["flags"]})
    ranked = sorted([o for o in out if o["status"] == "ranked"], key=lambda o: -o["score"])
    for i, o in enumerate(ranked, 1):
        o["rank"] = i
    order = {"ranked": 0, "flagged": 1, "ineligible": 2}
    out.sort(key=lambda o: (order[o["status"]], o["rank"] or 99, -(o["score"] or 0)))
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--offline", action="store_true")
    g.add_argument("--live", action="store_true")
    args = ap.parse_args()

    audit = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(), "criteria_version": CRITERIA["version"],
             "mode": "live" if args.live else "offline"}
    if args.offline:
        extractions = json.loads((HERE / "fixtures/extracted_fixtures.json").read_text(encoding="utf-8"))
    else:
        sp = load_system_prompt()
        audit["prompt_sha256"] = hashlib.sha256(sp.encode()).hexdigest()
        extractions = {}
        for f in sorted((HERE / "samples").glob("*.txt")):
            text = f.read_text(encoding="utf-8")
            data, model = extract_live(text, sp)
            audit["model"] = model
            bad = verify_evidence(data, text)
            if bad:
                print(f"[{f.stem}] quotes not found in source for fields {bad}; marking as unclear")
                for k in bad:
                    if k in data:
                        data[k] = None
            if INJECTION_PATTERNS.search(text):
                data["reviewer_instructions_detected"] = True
            extractions[f.stem] = data
            audit.setdefault("inputs", {})[f.stem] = hashlib.sha256(text.encode()).hexdigest()

    if not extractions:
        sys.exit("No proposals found. Add A.txt ... E.txt to prototype/samples/ (or use --offline).")

    results = run(extractions)
    OUT.mkdir(exist_ok=True)
    (OUT / "ranking.generated.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (OUT / "audit.json").write_text(json.dumps({**audit, "extractions": extractions}, indent=2), encoding="utf-8")
    for r in results:
        print(f"{r['proposal']}  {r['status']:<10} rank={r['rank']}  score={r['score']}  {r.get('breakdown')}  {r.get('flags') or r['reason']}")


if __name__ == "__main__":
    main()