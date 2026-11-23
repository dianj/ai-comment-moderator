"""The moderation pipeline: detectors, then (only if needed) the LLM and the decision gate in parallel, then the
policy."""
import asyncio
import logging
import time
from dataclasses import dataclass, field

from . import config, decisions, detectors, llm, policy
from .prompts import PROMPT_VERSION

log = logging.getLogger("moderator.pipeline")


@dataclass
class ModerationResult:
    decision: policy.Decision
    details: dict = field(default_factory=dict)   # stored in the audit log


def gate_text(author: str, content: str) -> str:
    return f"Author: {author}\nComment:\n{content}"


async def moderate(author: str, content: str) -> ModerationResult:
    start = time.perf_counter()
    findings = detectors.scan(f"{author}\n{content}")
    details = {"findings": [{"kind": f.kind, "value": f.value} for f in findings]}

    decision = policy.decide_without_llm(content, detectors.personal_data(findings),
                                         detectors.is_trivially_empty(content))
    if decision is None:
        details.update(model=config.MODEL_NAME, prompt_version=PROMPT_VERSION,
                       reasoning_effort=config.REASONING_EFFORT or "default")
        gate_task = None
        if config.DECISION_GATE:
            gate_task = asyncio.create_task(decisions.decider().ask(decisions.OUTCOME, gate_text(author, content)))
        try:
            result = await llm.classify(author, content)
        except llm.LLMError as e:
            log.exception("Moderation call failed; queueing the comment for human review")
            details["error"] = str(e)
            decision = policy.fallback()
        else:
            v = result.verdict
            decision = policy.decide_from_verdict(v.decision, v.category, v.toxicity_score, v.reason)
            details.update(model_decision=v.decision, raw=result.raw, llm_latency_ms=result.latency_ms,
                           reasoning_tokens=result.reasoning_tokens)
        if gate_task is not None:
            gate = await gate_task           # never raises: an unreachable model is an "unknown" decision
            details["gate"] = gate.record.model_dump(mode="json")
            decision = policy.apply_gate(decision, gate)

    details.update(rule=decision.rule, total_latency_ms=int((time.perf_counter() - start) * 1000))
    return ModerationResult(decision, details)
