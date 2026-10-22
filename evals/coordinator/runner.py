"""Evaluation runner for coordinator single decision models and LLM baselines.

Implements the single decision model evaluation specification from
to-do-tasks/evaluate-coordinator-models.md.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from adan.config import Settings
from adan.prompts import ROUTER, SOURCE_SCOPE

logger = logging.getLogger("coordinator_eval")

Q_DOCS = (
    "Does answering require consulting the supplied CloudScale policy documents, "
    "including checking for missing requested policy information?"
)
Q_DB = (
    "Does answering require retrieving actual customer, subscription, or incident "
    "records from the supplied database, beyond facts explicitly provided in the "
    "question/context?"
)

CANONICAL_ROUTES = ["direct", "document", "database", "hybrid"]


def flags_to_route(needs_docs: bool, needs_db: bool) -> str:
    if needs_docs and needs_db:
        return "hybrid"
    if needs_docs:
        return "document"
    if needs_db:
        return "database"
    return "direct"


def compute_payload_hash(data: Any) -> str:
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def redact_secrets(headers: dict[str, str]) -> dict[str, str]:
    sanitized = {}
    for k, v in headers.items():
        if k.lower() in ("authorization", "x-api-key", "api-key"):
            sanitized[k] = "Bearer [REDACTED]" if " " in v else "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


@dataclass
class AttemptRecord:
    attempt: int
    started_at: str
    finished_at: str
    duration_ms: float
    status: str
    http_status: Optional[int] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    endpoint: str = ""
    request_headers_sanitized: dict[str, str] = field(default_factory=dict)
    request_payload: dict[str, Any] = field(default_factory=dict)
    raw_response: Optional[dict[str, Any]] = None


@dataclass
class DecisionOutput:
    candidate_id: str
    case_id: str
    split: str
    trial: int
    input_hash: str
    p_docs: Optional[float]
    p_db: Optional[float]
    threshold_docs: Optional[float]
    threshold_db: Optional[float]
    pred_needs_docs: Optional[bool]
    pred_needs_db: Optional[bool]
    predicted_route: Optional[str]
    expected_route: str
    expected_needs_docs: bool
    expected_needs_db: bool
    is_route_correct: Optional[bool]
    is_docs_correct: Optional[bool]
    is_db_correct: Optional[bool]
    status: str  # ok, error, timeout, auth_error
    total_duration_ms: float
    attempts: list[AttemptRecord]
    usage: dict[str, Any] = field(default_factory=dict)
    cost: Optional[float] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    group_id: str = ""
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class CandidateAdapter:
    def __init__(self, config: dict[str, Any], api_key: str):
        self.config = config
        self.candidate_id = config["id"]
        self.display_name = config.get("display_name", self.candidate_id)
        self.api_key = api_key
        self.model = config["model"]
        self.base_url = config["base_url"].rstrip("/")
        self.timeout = config.get("timeout_seconds", 30)
        self.max_retries = config.get("max_transient_retries", 1)
        self.is_probability_model = config.get("is_probability_model", False)

    async def evaluate_case(
        self,
        case: dict[str, Any],
        trial: int,
        client: httpx.AsyncClient,
        threshold_docs: float = 0.5,
        threshold_db: float = 0.5,
    ) -> DecisionOutput:
        raise NotImplementedError


class OpenRouterDecisionsAdapter(CandidateAdapter):
    """Adapter for models running through OpenRouter /api/alpha/decisions (Mammoth-1)."""

    def build_payload(self, case: dict[str, Any]) -> Tuple[str, dict[str, Any]]:
        question = case["question"]
        context = case.get("input_context", [])
        state = f"{SOURCE_SCOPE}\n\nUser Question:\n{question}"
        if context:
            state += "\n\nContext & Assumptions:\n" + "\n".join(f"- {c}" for c in context)

        payload = {
            "model": self.model,
            "state": state,
            "questions": {
                "needs_docs": {
                    "type": "choice",
                    "instructions": Q_DOCS,
                    "criteria": {
                        "true": "Requires consulting CloudScale policy documents",
                        "false": "Does not require consulting CloudScale policy documents",
                    },
                },
                "needs_db": {
                    "type": "choice",
                    "instructions": Q_DB,
                    "criteria": {
                        "true": "Requires retrieving database customer/incident records",
                        "false": "Does not require retrieving database customer/incident records",
                    },
                },
            },
        }
        return state, payload

    async def evaluate_case(
        self,
        case: dict[str, Any],
        trial: int,
        client: httpx.AsyncClient,
        threshold_docs: float = 0.5,
        threshold_db: float = 0.5,
    ) -> DecisionOutput:
        state, payload = self.build_payload(case)
        input_hash = compute_payload_hash(payload)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        attempts: list[AttemptRecord] = []
        p_docs: Optional[float] = None
        p_db: Optional[float] = None
        usage: dict[str, Any] = {}
        cost: Optional[float] = None
        overall_status = "error"
        total_duration = 0.0

        for attempt_idx in range(self.max_retries + 1):
            started_at = datetime.now(UTC).isoformat()
            t0 = time.monotonic()
            att = AttemptRecord(
                attempt=attempt_idx + 1,
                started_at=started_at,
                finished_at="",
                duration_ms=0.0,
                status="running",
                endpoint=self.base_url,
                request_headers_sanitized=redact_secrets(headers),
                request_payload=payload,
            )
            try:
                res = await client.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                att.http_status = res.status_code
                dur = (time.monotonic() - t0) * 1000
                att.duration_ms = dur
                total_duration += dur
                att.finished_at = datetime.now(UTC).isoformat()

                if res.status_code == 200:
                    data = res.json()
                    att.raw_response = data
                    att.status = "ok"
                    overall_status = "ok"

                    answers = data.get("answers", {})
                    docs_info = answers.get("needs_docs", {})
                    db_info = answers.get("needs_db", {})

                    p_docs = float(
                        docs_info.get("probabilities", {}).get(
                            "true", 1.0 if docs_info.get("choice") == "true" else 0.0
                        )
                    )
                    p_db = float(
                        db_info.get("probabilities", {}).get(
                            "true", 1.0 if db_info.get("choice") == "true" else 0.0
                        )
                    )

                    usage = data.get("usage", {})
                    cost = usage.get("cost")
                    attempts.append(att)
                    break
                else:
                    att.status = "http_error"
                    att.error = f"HTTP {res.status_code}: {res.text[:300]}"
                    att.raw_response = res.json() if res.headers.get("content-type", "").startswith("application/json") else {"text": res.text[:300]}
                    if res.status_code in (401, 403):
                        overall_status = "auth_error"
                        attempts.append(att)
                        break
                    if res.status_code == 429 or res.status_code >= 500:
                        overall_status = "rate_limit" if res.status_code == 429 else "server_error"
                        attempts.append(att)
                        if attempt_idx < self.max_retries:
                            await asyncio.sleep(2.0 * (attempt_idx + 1))
                            continue
                    attempts.append(att)
                    break
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                dur = (time.monotonic() - t0) * 1000
                total_duration += dur
                att.duration_ms = dur
                att.finished_at = datetime.now(UTC).isoformat()
                att.status = "timeout"
                att.error = str(exc)
                overall_status = "timeout"
                attempts.append(att)
                if attempt_idx < self.max_retries:
                    await asyncio.sleep(1.0)
                    continue
                break
            except Exception as exc:
                dur = (time.monotonic() - t0) * 1000
                total_duration += dur
                att.duration_ms = dur
                att.finished_at = datetime.now(UTC).isoformat()
                att.status = "error"
                att.error = str(exc)
                att.error_type = type(exc).__name__
                overall_status = "error"
                attempts.append(att)
                if attempt_idx < self.max_retries:
                    await asyncio.sleep(1.0)
                    continue
                break

        pred_docs = (p_docs >= threshold_docs) if p_docs is not None else None
        pred_db = (p_db >= threshold_db) if p_db is not None else None
        pred_route = flags_to_route(pred_docs, pred_db) if (pred_docs is not None and pred_db is not None) else None

        exp_docs = case["expected_needs_docs"]
        exp_db = case["expected_needs_db"]
        exp_route = case["expected_route"]

        is_route_correct = (pred_route == exp_route) if pred_route is not None else None
        is_docs_correct = (pred_docs == exp_docs) if pred_docs is not None else None
        is_db_correct = (pred_db == exp_db) if pred_db is not None else None

        return DecisionOutput(
            candidate_id=self.candidate_id,
            case_id=case["question_id"],
            split=case.get("split", "test"),
            trial=trial,
            input_hash=input_hash,
            p_docs=p_docs,
            p_db=p_db,
            threshold_docs=threshold_docs,
            threshold_db=threshold_db,
            pred_needs_docs=pred_docs,
            pred_needs_db=pred_db,
            predicted_route=pred_route,
            expected_route=exp_route,
            expected_needs_docs=exp_docs,
            expected_needs_db=exp_db,
            is_route_correct=is_route_correct,
            is_docs_correct=is_docs_correct,
            is_db_correct=is_db_correct,
            status=overall_status,
            total_duration_ms=round(total_duration, 2),
            attempts=attempts,
            usage=usage,
            cost=cost,
            group_id=case.get("group_id", ""),
            tags=case.get("tags", []),
        )


class ChatCompletionsAdapter(CandidateAdapter):
    """Structured output LLM baseline using standard /api/v1/chat/completions."""

    def build_payload(self, case: dict[str, Any]) -> Tuple[dict[str, Any], dict[str, Any]]:
        question = case["question"]
        context = case.get("input_context", [])
        user_content = json.dumps({"question": question, "input_context": context}, ensure_ascii=False)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": ROUTER},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        return {"question": question, "input_context": context}, payload

    async def evaluate_case(
        self,
        case: dict[str, Any],
        trial: int,
        client: httpx.AsyncClient,
        threshold_docs: float = 0.5,
        threshold_db: float = 0.5,
    ) -> DecisionOutput:
        user_input, payload = self.build_payload(case)
        input_hash = compute_payload_hash(payload)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        attempts: list[AttemptRecord] = []
        pred_docs: Optional[bool] = None
        pred_db: Optional[bool] = None
        usage: dict[str, Any] = {}
        cost: Optional[float] = None
        overall_status = "error"
        total_duration = 0.0

        for attempt_idx in range(self.max_retries + 1):
            started_at = datetime.now(UTC).isoformat()
            t0 = time.monotonic()
            att = AttemptRecord(
                attempt=attempt_idx + 1,
                started_at=started_at,
                finished_at="",
                duration_ms=0.0,
                status="running",
                endpoint=self.base_url,
                request_headers_sanitized=redact_secrets(headers),
                request_payload=payload,
            )
            try:
                res = await client.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                att.http_status = res.status_code
                dur = (time.monotonic() - t0) * 1000
                att.duration_ms = dur
                total_duration += dur
                att.finished_at = datetime.now(UTC).isoformat()

                if res.status_code == 200:
                    data = res.json()
                    att.raw_response = data
                    choices = data.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        content = msg.get("content", "").strip()
                        # Parse JSON from content
                        parsed = json.loads(content)
                        pred_docs = bool(parsed.get("needs_docs"))
                        pred_db = bool(parsed.get("needs_db"))
                        att.status = "ok"
                        overall_status = "ok"
                    else:
                        att.status = "empty_choice"
                        att.error = "No choices returned by LLM"

                    usage = data.get("usage", {})
                    cost = usage.get("cost")
                    attempts.append(att)
                    break
                else:
                    att.status = "http_error"
                    att.error = f"HTTP {res.status_code}: {res.text[:300]}"
                    if res.status_code in (401, 403):
                        overall_status = "auth_error"
                        attempts.append(att)
                        break
                    if res.status_code == 429 or res.status_code >= 500:
                        overall_status = "rate_limit" if res.status_code == 429 else "server_error"
                        attempts.append(att)
                        if attempt_idx < self.max_retries:
                            await asyncio.sleep(2.0 * (attempt_idx + 1))
                            continue
                    attempts.append(att)
                    break
            except Exception as exc:
                dur = (time.monotonic() - t0) * 1000
                total_duration += dur
                att.duration_ms = dur
                att.finished_at = datetime.now(UTC).isoformat()
                att.status = "error"
                att.error = str(exc)
                att.error_type = type(exc).__name__
                overall_status = "error"
                attempts.append(att)
                if attempt_idx < self.max_retries:
                    await asyncio.sleep(1.0)
                    continue
                break

        pred_route = flags_to_route(pred_docs, pred_db) if (pred_docs is not None and pred_db is not None) else None
        exp_docs = case["expected_needs_docs"]
        exp_db = case["expected_needs_db"]
        exp_route = case["expected_route"]

        is_route_correct = (pred_route == exp_route) if pred_route is not None else None
        is_docs_correct = (pred_docs == exp_docs) if pred_docs is not None else None
        is_db_correct = (pred_db == exp_db) if pred_db is not None else None

        return DecisionOutput(
            candidate_id=self.candidate_id,
            case_id=case["question_id"],
            split=case.get("split", "test"),
            trial=trial,
            input_hash=input_hash,
            p_docs=None,
            p_db=None,
            threshold_docs=None,
            threshold_db=None,
            pred_needs_docs=pred_docs,
            pred_needs_db=pred_db,
            predicted_route=pred_route,
            expected_route=exp_route,
            expected_needs_docs=exp_docs,
            expected_needs_db=exp_db,
            is_route_correct=is_route_correct,
            is_docs_correct=is_docs_correct,
            is_db_correct=is_db_correct,
            status=overall_status,
            total_duration_ms=round(total_duration, 2),
            attempts=attempts,
            usage=usage,
            cost=cost,
            group_id=case.get("group_id", ""),
            tags=case.get("tags", []),
        )


class SanityBaselineAdapter(CandidateAdapter):
    """Zero-request sanity baseline: always-documents, always-both, always-direct."""

    def __init__(self, baseline_name: str, fixed_docs: bool, fixed_db: bool):
        super().__init__(
            {"id": baseline_name, "display_name": f"Sanity Baseline ({baseline_name})", "model": baseline_name, "base_url": "sanity://local"},
            "",
        )
        self.fixed_docs = fixed_docs
        self.fixed_db = fixed_db
        self.fixed_route = flags_to_route(fixed_docs, fixed_db)

    async def evaluate_case(
        self,
        case: dict[str, Any],
        trial: int,
        client: httpx.AsyncClient,
        threshold_docs: float = 0.5,
        threshold_db: float = 0.5,
    ) -> DecisionOutput:
        exp_docs = case["expected_needs_docs"]
        exp_db = case["expected_needs_db"]
        exp_route = case["expected_route"]

        return DecisionOutput(
            candidate_id=self.candidate_id,
            case_id=case["question_id"],
            split=case.get("split", "test"),
            trial=trial,
            input_hash="sanity_zero_request",
            p_docs=1.0 if self.fixed_docs else 0.0,
            p_db=1.0 if self.fixed_db else 0.0,
            threshold_docs=None,
            threshold_db=None,
            pred_needs_docs=self.fixed_docs,
            pred_needs_db=self.fixed_db,
            predicted_route=self.fixed_route,
            expected_route=exp_route,
            expected_needs_docs=exp_docs,
            expected_needs_db=exp_db,
            is_route_correct=(self.fixed_route == exp_route),
            is_docs_correct=(self.fixed_docs == exp_docs),
            is_db_correct=(self.fixed_db == exp_db),
            status="ok",
            total_duration_ms=0.0,
            attempts=[],
            usage={"input_tokens": 0, "output_tokens": 0, "cost": 0.0},
            cost=0.0,
            group_id=case.get("group_id", ""),
            tags=case.get("tags", []),
        )


# ---------------------------------------------------------------------------
# Calibration Logic
# ---------------------------------------------------------------------------


def calibrate_thresholds(
    dev_outputs: list[DecisionOutput],
) -> Tuple[float, float, dict[str, Any]]:
    """Tune thresholds on development cases only, searching 0.20-0.80 step 0.05.

    Loss function: 5 * false_negatives + false_positives per flag.
    Ties: closest to 0.5, then lower threshold.
    """
    threshold_grid = [round(0.20 + 0.05 * i, 2) for i in range(13)]  # 0.20 to 0.80

    def tune_flag(flag: str) -> Tuple[float, dict[str, Any]]:
        best_tau = 0.5
        best_loss = float("inf")
        grid_search_log = []

        for tau in threshold_grid:
            fn = 0
            fp = 0
            tp = 0
            tn = 0
            for item in dev_outputs:
                prob = item.p_docs if flag == "docs" else item.p_db
                gold = item.expected_needs_docs if flag == "docs" else item.expected_needs_db
                if prob is None:
                    continue
                pred = prob >= tau
                if gold and not pred:
                    fn += 1
                elif not gold and pred:
                    fp += 1
                elif gold and pred:
                    tp += 1
                else:
                    tn += 1

            loss = 5 * fn + fp
            grid_search_log.append(
                {"tau": tau, "loss": loss, "fn": fn, "fp": fp, "tp": tp, "tn": tn}
            )

            # Check if this tau is strictly better, or tie breaker (closest to 0.5, then lower)
            is_better = False
            if loss < best_loss:
                is_better = True
            elif loss == best_loss:
                dist_current = abs(tau - 0.5)
                dist_best = abs(best_tau - 0.5)
                if dist_current < dist_best - 1e-6:
                    is_better = True
                elif abs(dist_current - dist_best) < 1e-6 and tau < best_tau:
                    is_better = True

            if is_better:
                best_loss = loss
                best_tau = tau

        return best_tau, {"best_tau": best_tau, "best_loss": best_loss, "grid": grid_search_log}

    tau_docs, docs_details = tune_flag("docs")
    tau_db, db_details = tune_flag("db")
    return tau_docs, tau_db, {"docs": docs_details, "db": db_details}


# ---------------------------------------------------------------------------
# Metrics Calculation
# ---------------------------------------------------------------------------


def calculate_metrics(
    outputs: list[DecisionOutput],
    total_planned_trials: Optional[int] = None,
) -> dict[str, Any]:
    """Computes exact 4-route accuracy, macro-F1, confusion matrix, per-flag metrics,

    missing-source rate, and latency/cost statistics.
    """
    total_outputs = len(outputs)
    planned = total_planned_trials or total_outputs

    valid_decisions = [o for o in outputs if o.status == "ok" and o.predicted_route is not None]
    valid_count = len(valid_decisions)

    # 4x4 Confusion matrix
    matrix = {exp: {pred: 0 for pred in CANONICAL_ROUTES} for exp in CANONICAL_ROUTES}
    for o in valid_decisions:
        if o.expected_route in matrix and o.predicted_route in matrix[o.expected_route]:
            matrix[o.expected_route][o.predicted_route] += 1

    # Per-route precision, recall, F1
    per_route = {}
    f1_list = []
    for r in CANONICAL_ROUTES:
        tp = matrix[r][r]
        fp = sum(matrix[other][r] for other in CANONICAL_ROUTES if other != r)
        fn = sum(matrix[r][other] for other in CANONICAL_ROUTES if other != r)

        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        recall = tp / (tp + fn) if (tp + fn) > 0 else None
        f1 = (2 * precision * recall / (precision + recall)) if (precision is not None and recall is not None and (precision + recall) > 0) else None

        per_route[r] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4) if precision is not None else "not_applicable",
            "recall": round(recall, 4) if recall is not None else "not_applicable",
            "f1": round(f1, 4) if f1 is not None else "not_applicable",
        }
        if f1 is not None:
            f1_list.append(f1)

    macro_f1 = sum(f1_list) / len(CANONICAL_ROUTES) if len(f1_list) == len(CANONICAL_ROUTES) else (sum(f1_list) / len(f1_list) if f1_list else 0.0)

    # Exact route accuracy
    correct_valid = sum(1 for o in valid_decisions if o.is_route_correct)
    accuracy_valid = (correct_valid / valid_count) if valid_count > 0 else 0.0
    accuracy_planned = (correct_valid / planned) if planned > 0 else 0.0

    # Per-flag metrics (needs_docs & needs_db)
    def compute_flag_metrics(flag: str):
        tp = fp = fn = tn = 0
        for o in valid_decisions:
            pred = o.pred_needs_docs if flag == "docs" else o.pred_needs_db
            gold = o.expected_needs_docs if flag == "docs" else o.expected_needs_db
            if pred and gold:
                tp += 1
            elif pred and not gold:
                fp += 1
            elif not pred and gold:
                fn += 1
            else:
                tn += 1

        p = tp / (tp + fp) if (tp + fp) > 0 else None
        r = tp / (tp + fn) if (tp + fn) > 0 else None
        f1 = (2 * p * r / (p + r)) if (p is not None and r is not None and (p + r) > 0) else None

        return {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": round(p, 4) if p is not None else "not_applicable",
            "recall": round(r, 4) if r is not None else "not_applicable",
            "f1": round(f1, 4) if f1 is not None else "not_applicable",
        }

    docs_metrics = compute_flag_metrics("docs")
    db_metrics = compute_flag_metrics("db")

    # Missing-source rate & Unnecessary-source rate
    missing_source_count = sum(
        1 for o in valid_decisions
        if (o.expected_needs_docs and not o.pred_needs_docs) or (o.expected_needs_db and not o.pred_needs_db)
    )
    unnecessary_source_count = sum(
        1 for o in valid_decisions
        if (not o.expected_needs_docs and o.pred_needs_docs) or (not o.expected_needs_db and o.pred_needs_db)
    )

    missing_source_rate = missing_source_count / valid_count if valid_count > 0 else 0.0
    unnecessary_source_rate = unnecessary_source_count / valid_count if valid_count > 0 else 0.0

    # Latency percentiles & stats
    durations = [o.total_duration_ms for o in valid_decisions]
    all_durations = [o.total_duration_ms for o in outputs]
    durations.sort()

    def percentile(data: list[float], p: float) -> float:
        if not data:
            return 0.0
        k = (len(data) - 1) * p
        f = int(k)
        c = f + 1
        if c < len(data):
            return data[f] + (data[c] - data[f]) * (k - f)
        return data[f]

    p50_latency = round(percentile(durations, 0.50), 2)
    p95_latency = round(percentile(durations, 0.95), 2)
    mean_latency = round(sum(durations) / len(durations), 2) if durations else 0.0

    # Token usage & Cost
    total_input_tokens = sum(o.usage.get("input_tokens", o.usage.get("prompt_tokens", 0)) for o in outputs)
    total_output_tokens = sum(o.usage.get("output_tokens", o.usage.get("completion_tokens", 0)) for o in outputs)
    costs = [o.cost for o in outputs if o.cost is not None]
    total_cost = sum(costs) if costs else (0.0 if any(o.cost == 0 for o in outputs) else None)

    # Reliability & Errors
    status_counts = Counter(o.status for o in outputs)
    fallback_count = sum(1 for o in outputs if o.fallback_used)

    return {
        "planned_trials": planned,
        "evaluated_trials": total_outputs,
        "valid_decisions": valid_count,
        "valid_decision_rate": round(valid_count / total_outputs, 4) if total_outputs > 0 else 0.0,
        "exact_route_accuracy_valid": round(accuracy_valid, 4),
        "exact_route_accuracy_all_planned": round(accuracy_planned, 4),
        "macro_f1": round(macro_f1, 4),
        "per_route": per_route,
        "confusion_matrix": matrix,
        "flags": {
            "needs_docs": docs_metrics,
            "needs_db": db_metrics,
        },
        "missing_source_count": missing_source_count,
        "missing_source_rate": round(missing_source_rate, 4),
        "unnecessary_source_count": unnecessary_source_count,
        "unnecessary_source_rate": round(unnecessary_source_rate, 4),
        "latency_ms": {
            "p50": p50_latency,
            "p95": p95_latency,
            "mean": mean_latency,
        },
        "tokens": {
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "avg_tokens_per_decision": round((total_input_tokens + total_output_tokens) / valid_count, 1) if valid_count > 0 else 0.0,
        },
        "cost": {
            "total_cost": total_cost,
            "cost_coverage": len(costs) / total_outputs if total_outputs > 0 else 0.0,
        },
        "status_counts": dict(status_counts),
        "fallback_count": fallback_count,
        "fallback_rate": round(fallback_count / total_outputs, 4) if total_outputs > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# Self Checks (Evaluator Integrity)
# ---------------------------------------------------------------------------


def run_evaluator_self_checks() -> bool:
    """Acceptance criterion check:

    Rejects invalid responses, missing outputs, label leakage, wrong flags, and
    broken denominators.
    """
    logger.info("Running evaluator self-checks...")

    # 1. Broken denominators check
    empty_metrics = calculate_metrics([], total_planned_trials=0)
    assert empty_metrics["valid_decisions"] == 0
    assert empty_metrics["exact_route_accuracy_valid"] == 0.0
    for r in CANONICAL_ROUTES:
        assert empty_metrics["per_route"][r]["precision"] == "not_applicable"
        assert empty_metrics["per_route"][r]["recall"] == "not_applicable"

    # 2. Label leakage check
    sample_case = {
        "question_id": "COORD-TEST-01",
        "question": "What is CloudScale refund policy?",
        "input_context": ["Assume user is enterprise."],
        "split": "development",
        "expected_needs_docs": True,
        "expected_needs_db": False,
        "expected_route": "document",
        "label_rationale": "Secret rationale should never leak.",
    }
    adapter = OpenRouterDecisionsAdapter(
        {"id": "test", "model": "baseten/mammoth-1:free", "base_url": "https://example.com"},
        "dummy_key",
    )
    state, payload = adapter.build_payload(sample_case)
    serialized_payload = json.dumps(payload)
    assert "Secret rationale should never leak" not in serialized_payload
    assert "expected_route" not in serialized_payload
    assert "expected_needs_docs" not in serialized_payload
    assert "expected_needs_db" not in serialized_payload

    # 3. Route mapping consistency
    assert flags_to_route(False, False) == "direct"
    assert flags_to_route(True, False) == "document"
    assert flags_to_route(False, True) == "database"
    assert flags_to_route(True, True) == "hybrid"

    # 4. Calibration tie-breaker verification
    # Dummy dev set where tau=0.45 and tau=0.55 have same loss
    # Closest to 0.5 (or tie) must be chosen deterministically
    dummy_dev = [
        DecisionOutput(
            candidate_id="mock", case_id="C1", split="development", trial=1, input_hash="h1",
            p_docs=0.48, p_db=0.1, threshold_docs=0.5, threshold_db=0.5,
            pred_needs_docs=False, pred_needs_db=False, predicted_route="direct",
            expected_route="document", expected_needs_docs=True, expected_needs_db=False,
            is_route_correct=False, is_docs_correct=False, is_db_correct=True,
            status="ok", total_duration_ms=10.0, attempts=[],
        ),
        DecisionOutput(
            candidate_id="mock", case_id="C2", split="development", trial=1, input_hash="h2",
            p_docs=0.52, p_db=0.9, threshold_docs=0.5, threshold_db=0.5,
            pred_needs_docs=True, pred_needs_db=True, predicted_route="hybrid",
            expected_route="hybrid", expected_needs_docs=True, expected_needs_db=True,
            is_route_correct=True, is_docs_correct=True, is_db_correct=True,
            status="ok", total_duration_ms=10.0, attempts=[],
        ),
    ]
    t_docs, t_db, _ = calibrate_thresholds(dummy_dev)
    assert 0.20 <= t_docs <= 0.80
    assert 0.20 <= t_db <= 0.80

    logger.info("Evaluator self-checks passed successfully.")
    return True


# ---------------------------------------------------------------------------
# Runner Execution Engine
# ---------------------------------------------------------------------------


class CoordinatorEvaluator:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        with open(config_path) as f:
            self.config = json.load(f)

        self.settings = Settings()
        self.api_key = self.settings.openrouter_api_key.get_secret_value()

        self.benchmark_file = Path(self.config.get("benchmark_file", "evals/coordinator/benchmark.jsonl"))
        self.rag_file = Path(self.config.get("rag_regression_file", "evals/rag/benchmark.jsonl"))
        self.output_dir = Path(self.config.get("output_directory", "experiments"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "traces").mkdir(parents=True, exist_ok=True)

        self.concurrency = self.config.get("concurrency", 2)
        self.rate_limit_delay = self.config.get("rate_limit_delay_seconds", 0.5)

    def load_benchmark(self, custom_path: Optional[Path] = None) -> list[dict[str, Any]]:
        target = custom_path or self.benchmark_file
        records = []
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def validate_benchmark(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Validates benchmark format, distribution, group isolation, and splits."""
        seen_ids = set()
        group_to_split: dict[str, set[str]] = {}
        route_counter = Counter()
        split_counter = Counter()

        for idx, r in enumerate(records):
            qid = r.get("question_id")
            assert qid, f"Record {idx} missing question_id"
            assert qid not in seen_ids, f"Duplicate question_id {qid}"
            seen_ids.add(qid)

            assert r.get("question"), f"{qid} has empty question"
            assert isinstance(r.get("input_context"), list), f"{qid} invalid input_context"
            assert r.get("expected_route") in CANONICAL_ROUTES, f"{qid} invalid expected_route"
            assert isinstance(r.get("expected_needs_docs"), bool), f"{qid} invalid expected_needs_docs"
            assert isinstance(r.get("expected_needs_db"), bool), f"{qid} invalid expected_needs_db"

            # Check route/flag consistency
            calc_route = flags_to_route(r["expected_needs_docs"], r["expected_needs_db"])
            assert calc_route == r["expected_route"], f"{qid} flag-route mismatch: flags say {calc_route}, route says {r['expected_route']}"

            split = r.get("split", "test")
            split_counter[split] += 1
            route_counter[r["expected_route"]] += 1

            gid = r.get("group_id")
            if gid:
                group_to_split.setdefault(gid, set()).add(split)

        # Ensure no group crosses dev/test splits
        for gid, splits in group_to_split.items():
            assert len(splits) == 1, f"Group {gid} crosses multiple splits: {splits}"

        return {
            "total_cases": len(records),
            "splits": dict(split_counter),
            "routes": dict(route_counter),
            "groups": len(group_to_split),
        }

    async def run_candidate_on_dataset(
        self,
        adapter: CandidateAdapter,
        records: list[dict[str, Any]],
        trials: int = 1,
        threshold_docs: float = 0.5,
        threshold_db: float = 0.5,
    ) -> list[DecisionOutput]:
        semaphore = asyncio.Semaphore(self.concurrency)
        client = httpx.AsyncClient(timeout=35.0)
        results: list[DecisionOutput] = []

        candidate_trace_dir = self.output_dir / "traces" / adapter.candidate_id
        candidate_trace_dir.mkdir(parents=True, exist_ok=True)

        async def worker(case: dict[str, Any], trial_idx: int) -> DecisionOutput:
            async with semaphore:
                out = await adapter.evaluate_case(
                    case,
                    trial=trial_idx,
                    client=client,
                    threshold_docs=threshold_docs,
                    threshold_db=threshold_db,
                )
                # Write individual trace file
                trace_file = candidate_trace_dir / f"{case['question_id']}_trial_{trial_idx}.json"
                with open(trace_file, "w", encoding="utf-8") as f:
                    json.dump(asdict(out), f, indent=2, ensure_ascii=False)

                if self.rate_limit_delay > 0:
                    await asyncio.sleep(self.rate_limit_delay)
                return out

        tasks = []
        for trial_num in range(1, trials + 1):
            for case in records:
                tasks.append(worker(case, trial_num))

        results = await asyncio.gather(*tasks)
        await client.aclose()
        return list(results)

    async def execute_experiment(
        self,
        trials: int = 1,
        selected_case_ids: Optional[list[str]] = None,
        custom_benchmark_path: Optional[Path] = None,
        include_rag_regression: bool = False,
        candidate_filter: Optional[str] = None,
    ) -> dict[str, Any]:
        records = self.load_benchmark(custom_benchmark_path)
        if selected_case_ids:
            records = [r for r in records if r["question_id"] in selected_case_ids]

        stats = self.validate_benchmark(records)
        logger.info("Dataset validated: %s", stats)

        dev_cases = [r for r in records if r.get("split") == "development"]
        test_cases = [r for r in records if r.get("split") == "test"]

        # Load existing summary and results if appending
        summary_file = self.output_dir / "summary.json"
        results_file = self.output_dir / "results.jsonl"
        experiment_summary: dict[str, Any] = {
            "metadata": {
                "run_timestamp": datetime.now(UTC).isoformat(),
                "config": self.config,
                "dataset_statistics": stats,
                "trials_per_case": trials,
            },
            "calibration": {},
            "candidates": {},
        }
        if summary_file.exists():
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    old_summary = json.load(f)
                    experiment_summary["calibration"] = old_summary.get("calibration", {})
                    experiment_summary["candidates"] = old_summary.get("candidates", {})
            except Exception:
                pass

        all_trial_results: list[DecisionOutput] = []

        # Iterate through models in config
        models_to_run = self.config.get("models", [])
        if candidate_filter:
            models_to_run = [m for m in models_to_run if m["id"] == candidate_filter]

        for m_cfg in models_to_run:
            m_id = m_cfg["id"]
            adapter_type = m_cfg.get("adapter", "openrouter_decisions")
            logger.info("==================================================")
            logger.info("Evaluating Candidate: %s (%s)", m_cfg.get("display_name", m_id), m_cfg["model"])
            logger.info("==================================================")

            if adapter_type == "openrouter_decisions":
                adapter = OpenRouterDecisionsAdapter(m_cfg, self.api_key)

                # Dev split
                logger.info("[%s] Running development split (%d cases)...", m_id, len(dev_cases))
                dev_outputs = await self.run_candidate_on_dataset(
                    adapter, dev_cases, trials=trials, threshold_docs=0.5, threshold_db=0.5
                )
                all_trial_results.extend(dev_outputs)
                experiment_summary["candidates"][f"{m_id}_raw_dev"] = calculate_metrics(dev_outputs)

                # Calibration
                tau_docs, tau_db, calib_details = calibrate_thresholds(dev_outputs)
                experiment_summary["calibration"][m_id] = {
                    "model": m_cfg["model"],
                    "tau_docs": tau_docs,
                    "tau_db": tau_db,
                    "details": calib_details,
                }
                logger.info("[%s] Calibration complete: tau_docs=%s, tau_db=%s", m_id, tau_docs, tau_db)

                # Test split (raw at 0.5)
                logger.info("[%s] Running test split (%d cases)...", m_id, len(test_cases))
                test_outputs = await self.run_candidate_on_dataset(
                    adapter, test_cases, trials=trials, threshold_docs=0.5, threshold_db=0.5
                )
                all_trial_results.extend(test_outputs)
                experiment_summary["candidates"][f"{m_id}_raw_test_tau_0.5"] = calculate_metrics(test_outputs)

                # Test split (calibrated)
                test_calibrated_outputs = []
                for o in test_outputs:
                    if o.p_docs is not None and o.p_db is not None:
                        p_docs_cal = o.p_docs >= tau_docs
                        p_db_cal = o.p_db >= tau_db
                        route_cal = flags_to_route(p_docs_cal, p_db_cal)
                        o_cal = DecisionOutput(
                            candidate_id=f"{m_id}_calibrated",
                            case_id=o.case_id,
                            split=o.split,
                            trial=o.trial,
                            input_hash=o.input_hash,
                            p_docs=o.p_docs,
                            p_db=o.p_db,
                            threshold_docs=tau_docs,
                            threshold_db=tau_db,
                            pred_needs_docs=p_docs_cal,
                            pred_needs_db=p_db_cal,
                            predicted_route=route_cal,
                            expected_route=o.expected_route,
                            expected_needs_docs=o.expected_needs_docs,
                            expected_needs_db=o.expected_needs_db,
                            is_route_correct=(route_cal == o.expected_route),
                            is_docs_correct=(p_docs_cal == o.expected_needs_docs),
                            is_db_correct=(p_db_cal == o.expected_needs_db),
                            status=o.status,
                            total_duration_ms=o.total_duration_ms,
                            attempts=o.attempts,
                            usage=o.usage,
                            cost=o.cost,
                            group_id=o.group_id,
                            tags=o.tags,
                        )
                        test_calibrated_outputs.append(o_cal)
                        all_trial_results.append(o_cal)
                experiment_summary["candidates"][f"{m_id}_calibrated_test"] = calculate_metrics(test_calibrated_outputs)

                # Optional RAG regression slice
                if include_rag_regression and self.rag_file.exists():
                    logger.info("[%s] Running RAG regression slice (48 cases)...", m_id)
                    rag_records = []
                    with open(self.rag_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                raw_r = json.loads(line)
                                docs_needed = bool(raw_r.get("is_document_1_needed") or raw_r.get("is_document_2_needed"))
                                db_needed = bool(raw_r.get("is_database_needed"))
                                rag_records.append({
                                    "question_id": raw_r["question_id"],
                                    "question": raw_r["question"],
                                    "input_context": raw_r.get("input_context", []),
                                    "split": "rag_regression",
                                    "expected_needs_docs": docs_needed,
                                    "expected_needs_db": db_needed,
                                    "expected_route": flags_to_route(docs_needed, db_needed),
                                    "group_id": f"rag_{raw_r['question_id']}",
                                    "tags": ["rag_regression", raw_r.get("difficulty", "medium")],
                                })
                    rag_outputs = await self.run_candidate_on_dataset(
                        adapter, rag_records, trials=1, threshold_docs=tau_docs, threshold_db=tau_db
                    )
                    all_trial_results.extend(rag_outputs)
                    experiment_summary["candidates"][f"{m_id}_rag_regression_calibrated"] = calculate_metrics(rag_outputs)

            elif adapter_type == "chat_completions":
                adapter = ChatCompletionsAdapter(m_cfg, self.api_key)
                logger.info("[%s] Running Structured LLM baseline (%d cases)...", m_id, len(records))
                llm_outputs = await self.run_candidate_on_dataset(adapter, records, trials=trials)
                all_trial_results.extend(llm_outputs)
                llm_dev = [o for o in llm_outputs if o.split == "development"]
                llm_test = [o for o in llm_outputs if o.split == "test"]
                experiment_summary["candidates"][f"{m_id}_dev"] = calculate_metrics(llm_dev)
                experiment_summary["candidates"][f"{m_id}_test"] = calculate_metrics(llm_test)

        # Sanity Baselines (evaluate on test if not already present)
        if "sanity_always_documents_test" not in experiment_summary["candidates"]:
            logger.info("Evaluating Sanity Baselines...")
            sanity_docs = SanityBaselineAdapter("always_documents", True, False)
            sanity_both = SanityBaselineAdapter("always_both", True, True)
            sanity_direct = SanityBaselineAdapter("always_direct", False, False)
            test_sanity_docs = await self.run_candidate_on_dataset(sanity_docs, test_cases, trials=1)
            test_sanity_both = await self.run_candidate_on_dataset(sanity_both, test_cases, trials=1)
            test_sanity_direct = await self.run_candidate_on_dataset(sanity_direct, test_cases, trials=1)
            experiment_summary["candidates"]["sanity_always_documents_test"] = calculate_metrics(test_sanity_docs)
            experiment_summary["candidates"]["sanity_always_both_test"] = calculate_metrics(test_sanity_both)
            experiment_summary["candidates"]["sanity_always_direct_test"] = calculate_metrics(test_sanity_direct)

        # Write/Update Output Artifacts
        mode = "a" if candidate_filter and results_file.exists() else "w"
        with open(results_file, mode, encoding="utf-8") as f:
            for item in all_trial_results:
                f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(experiment_summary, f, indent=2, ensure_ascii=False)

        logger.info("Saved results to %s and %s", results_file, summary_file)
        return experiment_summary


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("evals/coordinator/config.json"))
    parser.add_argument("--dry-run", action="store_true", help="Validate setup without network requests")
    parser.add_argument("--self-check", action="store_true", help="Run local evaluator integrity self-checks")
    parser.add_argument("--candidate", type=str, default=None, help="Filter to specific candidate model ID (e.g. elephant_decision)")
    parser.add_argument("--regression", action="store_true", help="Include supplemental 48-case RAG regression slice")
    parser.add_argument("--trials", type=int, default=1, help="Number of trials per case")
    parser.add_argument("--samples", type=Path, help="Optional custom benchmark file")
    parser.add_argument("--output", type=Path, help="Override output directory")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.self_check:
        run_evaluator_self_checks()
        sys.exit(0)

    evaluator = CoordinatorEvaluator(args.config)
    if args.output:
        evaluator.output_dir = args.output
        evaluator.output_dir.mkdir(parents=True, exist_ok=True)
        (evaluator.output_dir / "traces").mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        records = evaluator.load_benchmark(args.samples)
        stats = evaluator.validate_benchmark(records)
        run_evaluator_self_checks()
        logger.info("DRY RUN SUCCESSFUL.")
        logger.info("Dataset statistics: %s", stats)
        logger.info("API Key loaded: %s", bool(evaluator.api_key))
        logger.info("Output directory: %s", evaluator.output_dir)
        sys.exit(0)

    # Run the full experiment
    asyncio.run(
        evaluator.execute_experiment(
            trials=args.trials,
            custom_benchmark_path=args.samples,
            include_rag_regression=args.regression,
            candidate_filter=args.candidate,
        )
    )


if __name__ == "__main__":
    main()

