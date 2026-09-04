"""Component I - human-readable PR feedback."""

from __future__ import annotations

from ..cost.reconcile import reconcile_estimate
from ..models import GateResult, Status, as_float
from .breakdown import (
    change_label,
    coverage_breakdown,
    ordered_resources,
    service_summary,
    top_service_drivers,
)

MARKER = "<!-- finops-cost-gate -->"

# A PR comment with hundreds of rows is unreadable and GitHub truncates it
# anyway. The full breakdown always lands in cost-estimate.json.
MAX_RESOURCE_ROWS = 15


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "n/a"
    return f"{currency} {value:,.2f}"


def _signed(value: float | None, currency: str) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{_money(value, currency)}"


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
        lines += [
            "### `FINOPS: BLOCKED`",
            "",
            "**Peer approval required.** Peer review is required before proceeding. "
            "No cost lock was created.",
            "",
            "This change exceeds the budget threshold and cannot continue on the normal "
            "path. A budget exception approved by another collaborator is required.",
        ]
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
        currency = estimate.currency
        rows = ordered_resources(estimate)
        shown = rows[:MAX_RESOURCE_ROWS]

        lines += [
            "",
            "### Cost breakdown",
            "",
            "| Resource | Service | Change | Monthly | Incremental |",
            "|---|---|---|---|---|",
        ]
        for resource in shown:
            lines.append(
                f"| `{resource.address}` | {resource.resource_type} | {change_label(resource)} | "
                f"{_money(as_float(resource.new_monthly_cost), currency)} | "
                f"{_signed(as_float(resource.delta_monthly_cost), currency)} |"
            )
        if len(rows) > len(shown):
            hidden = len(rows) - len(shown)
            lines += [
                "",
                f"_{hidden} further priced resource(s) omitted. The complete breakdown, "
                f"including every cost component, is in `cost-estimate.json` in this run's "
                f"`finops-{estimate.resources[0].cloud.value}` artifact._",
            ]

        services = service_summary(estimate)
        if services:
            lines += [
                "",
                "### Service summary",
                "",
                "| Service | Resources | Monthly | Incremental |",
                "|---|---|---|---|",
            ]
            for total in services:
                lines.append(
                    f"| {total.service} | {total.resource_count} | "
                    f"{_money(float(total.new_monthly_cost), currency)} | "
                    f"{_signed(float(total.delta_monthly_cost), currency)} |"
                )
            lines.append(
                f"| **Total (Infracost)** | {len(estimate.resources)} | "
                f"**{_money(as_float(estimate.new_monthly_cost), currency)}** | "
                f"**{_signed(as_float(estimate.incremental_monthly_cost), currency)}** |"
            )

        drivers = top_service_drivers(estimate)
        if drivers:
            lines += ["", "### Top cost drivers", "", "Ranked by actual monthly cost.", ""]
            for rank, total in enumerate(drivers, start=1):
                lines.append(
                    f"{rank}. **{total.service}** — Monthly cost "
                    f"{_money(float(total.new_monthly_cost), currency)} · "
                    f"Incremental impact {_signed(float(total.delta_monthly_cost), currency)}"
                )

        # Never let a resource Infracost could not price read as free.
        groups = coverage_breakdown(estimate)
        if groups:
            lines += ["", "### Coverage", "",
                      "| Classification | Resources | Monthly |", "|---|---|---|"]
            for label, items in groups.items():
                subtotal = sum((float(r.new_monthly_cost) for r in items), 0.0)
                lines.append(f"| {label} | {len(items)} | {_money(subtotal, currency)} |")
            unpriced = groups.get("UNSUPPORTED / UNESTIMATED", [])
            if unpriced:
                lines += ["", "Not estimated because usage data or pricing coverage is "
                          "unavailable - these are **not** zero-cost:"]
                lines += [f"- `{r.address}` ({r.resource_type})" for r in unpriced[:10]]

        # Observability only: Infracost's totals above stay authoritative even
        # when the per-resource rows do not add up to them.
        checks = reconcile_estimate(estimate)
        broken = [c for c in checks if not c.ok and not c.explained_by_coverage]
        lines += ["", "### Reconciliation", ""]
        for check in checks:
            prefix = "**MISMATCH** — " if check in broken else ""
            lines.append(f"- {prefix}{check.message(currency)}")
        if broken:
            lines.append(
                "- The Infracost totals shown above remain authoritative and drive the "
                "decision; the breakdown is reporting only."
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


def render_exception_banner(approval: dict) -> str:
    """Appended after a verified exception. The FAIL above is left intact."""
    approved = approval.get("exception_approval") == "APPROVED"
    currency = approval.get("currency") or ""
    lines = ["", "---", ""]
    if approved:
        lines += [
            "## ✅ Budget exception APPROVED",
            "",
            "The FinOps decision above is unchanged. This change remains over budget and "
            "was allowed to proceed only by an explicit, audited peer approval.",
            "",
            "| | |",
            "|---|---|",
            f"| FinOps decision | **{approval.get('finops_decision')}** (unchanged) |",
            f"| Exception approval | **{approval.get('exception_approval')}** |",
            f"| Approver | `{approval.get('approver')}` |",
            f"| Approved incremental cost | {currency} {approval.get('approved_incremental_cost')}/mo |",
            f"| Approved ceiling | {currency} {approval.get('max_incremental_cost')}/mo |",
            f"| Expires | {approval.get('expires_at')} |",
            f"| Exception id | `{approval.get('exception_id')}` |",
            "",
            "Re-approval is required if the Terraform change, the resolved configuration, "
            "the threshold, or the cost moves above the ceiling.",
        ]
    else:
        lines += [
            "## ⛔ Budget exception REJECTED",
            "",
            "`FINOPS: BLOCKED` — the supplied exception does not authorise this change.",
            "",
        ]
        lines += [f"- {p}" for p in approval.get("problems", [])]
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
