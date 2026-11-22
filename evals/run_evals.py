"""Moderation eval: run the labelled comments in evals/dataset.jsonl through the moderator
and score the verdicts.

Every case lists the decisions that count as correct (`expect`) and, for harmful content,
the categories that count as correct (`categories`). Besides plain accuracy the report
tracks the two errors that matter most for a comment section:

  * leaked       - harmful content that was published (APPROVED although it should not be)
  * over-blocked - acceptable content that was REJECTED outright

Usage:
  python evals/run_evals.py                      # all cases, once
  python evals/run_evals.py --repeat 3           # consistency across runs
  python evals/run_evals.py --only pii,injection-03
  python evals/run_evals.py --regrade evals/results/run-....json   # re-score saved verdicts
"""
import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "evals" / "dataset.jsonl"
RESULTS = ROOT / "evals" / "results"
FALLBACK_CATEGORY = "System Fallback"  # what the moderator returns when the LLM call or parsing fails


def load_cases(only=None):
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if only:
        keys = {k.strip() for k in only.split(",") if k.strip()}
        cases = [c for c in cases if c["id"] in keys or c["group"] in keys]
    return cases


def make_moderator(base_url, model):
    """Return (name, fn(author, content) -> verdict dict). Points the app at the given LM Studio."""
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    import server  # noqa: E402  (the prototype keeps everything in server.py)
    from openai import OpenAI

    server.llm_client = OpenAI(base_url=base_url, api_key="lm-studio")
    server.MODEL_NAME = model
    return "server.analyze_comment_with_ai", server.analyze_comment_with_ai


def grade(case, verdict):
    decision = verdict.get("decision")
    category = verdict.get("category")
    ok = decision in case["expect"]
    category_ok = None
    if case.get("categories") and decision != "APPROVED":
        category_ok = category in case["categories"]
    return {
        "ok": ok,
        "category_ok": category_ok,
        "leaked": decision == "APPROVED" and "APPROVED" not in case["expect"],
        "over_blocked": decision == "REJECTED" and "REJECTED" not in case["expect"],
        "fallback": category == FALLBACK_CATEGORY,
    }


def run(cases, moderate, repeat):
    records = []
    for r in range(repeat):
        for case in cases:
            start = time.perf_counter()
            verdict = moderate(case.get("author", "Читател"), case["content"])
            latency = time.perf_counter() - start
            rec = {"run": r + 1, "id": case["id"], "group": case["group"], "verdict": verdict,
                   "latency_s": round(latency, 2)}
            rec.update(grade(case, verdict))
            records.append(rec)
            mark = "PASS" if rec["ok"] else "FAIL"
            print(f"[{r + 1}/{repeat}] {mark} {case['id']:<16} {verdict.get('decision'):<12} "
                  f"{verdict.get('category')!s:<18} {latency:5.1f}s", flush=True)
    return records


def pct(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def report(meta, cases, records):
    by_id = {c["id"]: c for c in cases}
    total = len(records)
    harmful = [r for r in records if "APPROVED" not in by_id[r["id"]]["expect"]]
    acceptable = [r for r in records if "REJECTED" not in by_id[r["id"]]["expect"]]
    with_cat = [r for r in records if r["category_ok"] is not None]
    latencies = sorted(r["latency_s"] for r in records)
    p95 = latencies[max(0, int(round(0.95 * len(latencies))) - 1)] if latencies else 0

    lines = [
        "# Moderation eval results",
        "",
        f"- Date: {meta['date']}",
        f"- Model: `{meta['model']}` via LM Studio",
        f"- Target: `{meta['target']}`",
        f"- Cases: {len(cases)} × {meta['repeat']} run(s) = {total} verdicts",
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Correct decision | {pct(sum(r['ok'] for r in records), total)} |",
        f"| **Leaked** (harmful content published) | {pct(sum(r['leaked'] for r in harmful), len(harmful))} |",
        f"| **Over-blocked** (acceptable content rejected) | {pct(sum(r['over_blocked'] for r in acceptable), len(acceptable))} |",
        f"| Correct category (when not approved) | {pct(sum(r['category_ok'] for r in with_cat), len(with_cat))} |",
        f"| LLM/parse fallbacks | {pct(sum(r['fallback'] for r in records), total)} |",
        f"| Latency p50 / p95 | {statistics.median(latencies):.1f}s / {p95:.1f}s |" if latencies else "| Latency | n/a |",
        "",
        "## By group",
        "",
        "| Group | Correct | Leaked | Over-blocked |",
        "|---|---|---|---|",
    ]
    groups = defaultdict(list)
    for r in records:
        groups[r["group"]].append(r)
    for g, rs in groups.items():
        lines.append(f"| {g} | {pct(sum(r['ok'] for r in rs), len(rs))} | {sum(r['leaked'] for r in rs)} | "
                     f"{sum(r['over_blocked'] for r in rs)} |")

    failures = [r for r in records if not r["ok"] or r["category_ok"] is False]
    lines += ["", "## Failures", ""]
    if not failures:
        lines.append("None.")
    else:
        lines += ["| Case | Run | Expected | Got | Reason given by the model |", "|---|---|---|---|---|"]
        for r in failures:
            c = by_id[r["id"]]
            exp = "/".join(c["expect"]) + (f" ({', '.join(c['categories'])})" if c.get("categories") else "")
            v = r["verdict"]
            reason = str(v.get("reason", "")).replace("|", "\\|").replace("\n", " ")[:160]
            lines.append(f"| {r['id']} | {r['run']} | {exp} | {v.get('decision')} ({v.get('category')}) | {reason} |")

    counts = Counter((r["verdict"].get("decision"), r["verdict"].get("category")) for r in records)
    lines += ["", "## Verdict distribution", "", "| Decision | Category | Count |", "|---|---|---|"]
    for (d, c), n in counts.most_common():
        lines.append(f"| {d} | {c} | {n} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("LMSTUDIO_URL", "http://localhost:1235/v1"))
    ap.add_argument("--model", default=os.environ.get("MODERATION_MODEL", "gemma-4-26b-a4b-it"))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", help="comma-separated case ids and/or group names")
    ap.add_argument("--regrade", help="re-score a saved run-*.json with the current dataset labels")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.regrade:
        saved = json.loads(Path(args.regrade).read_text(encoding="utf-8"))
        meta, records = saved["meta"], saved["records"]
        cases = load_cases()
        by_id = {c["id"]: c for c in cases}
        records = [r for r in records if r["id"] in by_id]
        for r in records:
            r.update(grade(by_id[r["id"]], r["verdict"]))
        cases = [c for c in cases if c["id"] in {r["id"] for r in records}]
    else:
        cases = load_cases(args.only)
        if not cases:
            sys.exit("No cases match --only.")
        target, moderate = make_moderator(args.base_url, args.model)
        meta = {"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "model": args.model,
                "target": target, "repeat": args.repeat}
        records = run(cases, moderate, args.repeat)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (RESULTS / f"run-{stamp}.json").write_text(
            json.dumps({"meta": meta, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")

    md = report(meta, cases, records)
    if not args.only:
        (RESULTS / "latest.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
