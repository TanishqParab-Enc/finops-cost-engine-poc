"""Component I - human-readable PR feedback."""

from __future__ import annotations

from ..models import GateResult, Status, as_float

MARKER = "<!-- finops-cost-gate -->"


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "n/a"
    return f"{currency} {value:,.2f}"


def render_markdown(result: GateResult) -> str:
    lines: list[str] = [MARKER]
    decision = result.decision
    estimate = result.estimate

    if result.status is Status.PASS:
        lines.append("## ✅ FinOps Cost Check Passed")
    elif result.status is Status.FAIL:
        lines.append("## ❌ FinOps Cost Check Failed")
    else:
        lines.append("## ⛔ FinOps Cost Check Could Not Complete")

    lines.append("")

    if decision and estimate:
        currency = estimate.currency
        lines += [
            "| | |",
            "|---|---|",
            f"| Current monthly cost | {_money(as_float(estimate.previous_monthly_cost), currency)} |",
            f"| Projected monthly cost | {_money(as_float(estimate.new_monthly_cost), currency)} |",
            f"| **Estimated monthly impact** | **{_money(as_float(estimate.incremental_monthly_cost), currency)}** |",
            f"| Threshold ({decision.metric}) | {_money(as_float(decision.threshold_value), currency)} |",
            f"| Comparison | `observed {decision.comparison} threshold` |",
            f"| Status | **{decision.status.value}** |",
        ]
        if decision.status is Status.FAIL:
            lines.append(
                f"| Exceeded by | **{_money(as_float(decision.exceeded_by), currency)}** |"
            )
        lines.append("")

    if result.status is Status.PASS:
        lines.append("Cost has been locked for this CI/CD execution.")
        if result.cost_lock:
            lines.append("")
            lines.append(f"`lock_id: {result.cost_lock.get('lock_id')}`")
            lines.append(f"`plan_fingerprint: {result.cost_lock.get('plan_fingerprint')}`")
    elif result.status is Status.FAIL:
        lines.append("**Peer review is required before proceeding.** No cost lock was created.")
    else:
        lines.append(
            "The cost impact could not be established, so the pipeline failed safe. "
            "No cost lock was created."
        )

    if result.errors:
        lines += ["", "### Errors", ""]
        for error in result.errors:
            detail = f" — {error['detail']}" if error.get("detail") else ""
            lines.append(f"- **{error.get('category')}**: {error.get('message')}{detail}")

    if estimate and estimate.resources:
        lines += ["", "### Cost drivers", "", "| Resource | Cloud | Change |", "|---|---|---|"]
        for resource in estimate.top_cost_drivers(5):
            delta = as_float(resource.delta_monthly_cost) or 0.0
            sign = "+" if delta > 0 else ""
            lines.append(
                f"| `{resource.address}` | {resource.cloud.value} | "
                f"{sign}{_money(delta, estimate.currency)}/mo |"
            )

    ai = result.ai
    if ai and ai.available:
        lines += ["", "### AI analysis", "", ai.summary, "", f"**Why:** {ai.reason}"]
        if ai.cost_drivers:
            lines += ["", "**Primary cost drivers:**"]
            lines += [f"- {d}" for d in ai.cost_drivers[:5]]
        if ai.recommendation:
            lines += ["", f"**Recommendation:** {ai.recommendation}"]
    elif ai:
        lines += ["", f"_AI explanation unavailable ({ai.error}). Cost decision is unaffected._"]

    if estimate and estimate.warnings:
        lines += ["", "### Coverage warnings", ""]
        lines += [f"- {w}" for w in estimate.warnings]

    if estimate:
        lines += [
            "",
            "---",
            f"<sub>Cost source: `{estimate.estimator}` {estimate.estimator_version} "
            f"({estimate.trust.value}) · execution `{result.execution_id}` · commit `{result.commit[:12]}`</sub>",
        ]

    return "\n".join(lines) + "\n"


def render_console(result: GateResult) -> str:
    decision = result.decision
    estimate = result.estimate
    if not decision or not estimate:
        header = f"FinOps gate: {result.status.value}"
        errors = "\n".join(
            f"  ! {e.get('category')}: {e.get('message')}" for e in result.errors
        )
        return f"{header}\n{errors}" if errors else header

    currency = estimate.currency
    icon = {Status.PASS: "PASS", Status.FAIL: "FAIL", Status.ERROR: "ERROR"}[result.status]
    lines = [
        f"FinOps cost gate: {icon}",
        f"  previous      : {_money(as_float(estimate.previous_monthly_cost), currency)}/mo",
        f"  projected     : {_money(as_float(estimate.new_monthly_cost), currency)}/mo",
        f"  incremental   : {_money(as_float(estimate.incremental_monthly_cost), currency)}/mo",
        f"  metric        : {decision.metric}",
        f"  observed      : {as_float(decision.observed_value)}",
        f"  threshold     : {as_float(decision.threshold_value)} ({decision.unit})",
        f"  comparison    : observed {decision.comparison} threshold",
        f"  estimator     : {estimate.estimator} [{estimate.trust.value}]",
    ]
    for reason in decision.reasons:
        lines.append(f"  reason        : {reason}")
    for error in result.errors:
        lines.append(f"  error         : {error.get('category')}: {error.get('message')}")
    if result.cost_lock:
        lines.append(f"  cost lock     : {result.cost_lock.get('lock_id')}")
    return "\n".join(lines)
