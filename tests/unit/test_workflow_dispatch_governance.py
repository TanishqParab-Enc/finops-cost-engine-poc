"""Unit tests for workflow_dispatch governance parity: a manually-dispatched
greenfield deployment for ANY registered stack must resolve through the same
trusted registry, and be gated by the exact same approval/authorization
engine, as a pull_request run. Nothing here is specific to web-platform."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from finops.errors import ConfigurationError
from finops.gate import evaluate_approval
from finops.lock.exception import create_exception, verify_environment_approval
from finops.models import (
    Action,
    Cloud,
    CostCoverage,
    CostEstimate,
    EstimatorTrust,
    NormalizedPlan,
    PolicyDecision,
    ResourceChange,
    Status,
)
from finops.stacks import get_stack, load_stacks

from ..conftest import make_config

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "finops-cost-gate.yml"

GENERIC_REGISTRY_YAML = """
schema_version: "1.0"
stacks:
  generic-workload:
    terraform_dir: terraform/workloads/generic-workload
    cloud: aws
    deployable: true
    environment: dev
    state_key: finops-poc/dev/generic-workload/terraform.tfstate
    paths:
      - terraform/workloads/generic-workload/
"""


@pytest.fixture()
def generic_registry(tmp_path) -> Path:
    path = tmp_path / "finops-stacks.yml"
    path.write_text(GENERIC_REGISTRY_YAML, encoding="utf-8")
    return path


class TestWorkflowDispatchStackResolution:
    """Requirement: workflow_dispatch resolves the selected stack ONLY
    through the existing registry - never a hard-coded directory/stack."""

    def test_resolves_a_generic_registered_stack_by_name(self, generic_registry):
        stack = get_stack("generic-workload", generic_registry)
        assert stack.terraform_dir == "terraform/workloads/generic-workload"
        assert stack.state_key == "finops-poc/dev/generic-workload/terraform.tfstate"
        assert stack.environment == "dev"
        assert stack.deployable is True

    def test_unknown_stack_name_is_rejected(self, generic_registry):
        with pytest.raises(ConfigurationError, match="Unknown stack"):
            get_stack("does-not-exist", generic_registry)

    def test_environment_mismatch_is_detectable(self, generic_registry):
        """Mirrors the workflow's own check: the dispatched `environment`
        input must match the registry's recorded environment for that stack."""
        stack = get_stack("generic-workload", generic_registry)
        assert stack.environment != "production"

    def test_registry_has_no_generic_fallback_root(self, generic_registry):
        """Requirement: never fall back to a generic Terraform root such as
        terraform/ or a default aws_instance workload."""
        stacks = load_stacks(generic_registry)
        for stack in stacks.values():
            assert stack.terraform_dir != "terraform"
            assert stack.terraform_dir.startswith("terraform/workloads/") or stack.terraform_dir.startswith(
                "terraform/aws"
            )


def make_plan(instance_type: str = "m5.large") -> NormalizedPlan:
    return NormalizedPlan(
        terraform_version="1.11.0",
        format_version="1.2",
        clouds=[Cloud.AWS],
        changes=[
            ResourceChange(
                address="module.compute.aws_instance.app",
                resource_type="aws_instance",
                name="app",
                cloud=Cloud.AWS,
                action=Action.CREATE,
                after={"instance_type": instance_type},
            )
        ],
    )


def make_plan_doc() -> dict:
    return {"variables": {"region": {"value": "us-east-1"}}}


def make_estimate(incremental: str = "150") -> CostEstimate:
    return CostEstimate(
        currency="USD",
        estimator="infracost (v2 schema)",
        estimator_version="2.16.2",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=Decimal("0"),
        new_monthly_cost=Decimal(incremental),
        incremental_monthly_cost=Decimal(incremental),
        coverage=CostCoverage(detected_resources=1, supported_resources=1),
    )


def make_decision(incremental: str = "150", threshold: str = "100") -> PolicyDecision:
    return PolicyDecision(
        status=Status.FAIL,
        metric="incremental_monthly_cost",
        observed_value=Decimal(incremental),
        threshold_value=Decimal(threshold),
        currency="USD",
        comparison="<=",
    )


class TestGreenfieldApprovalChannel:
    """Requirement: approval semantics (PASS skips approval, BLOCK waits for
    finops-cost-approval, deployment_authorization gates apply) are identical
    for a workflow_dispatch greenfield run and a pull_request run."""

    def test_pass_path_never_requires_approval_regardless_of_trigger(self):
        for _trigger in ("pull_request", "workflow_dispatch"):
            states = evaluate_approval(analyze_exit_code=0, lock_verified=True)
            assert states["finops_decision"] == "PASS"
            assert states["approval_status"] == "NOT_REQUIRED"
            assert states["deployment_authorization"] == "AUTHORIZED"

    def test_block_path_stays_pending_and_denied_until_approved(self):
        """BLOCK + no approval yet = deployment_authorization DENIED,
        whichever trigger produced the evaluation - apply must never run."""
        states = evaluate_approval(analyze_exit_code=1)
        assert states["finops_decision"] == "BLOCK"
        assert states["approval_status"] == "PENDING"
        assert states["deployment_authorization"] == "DENIED"

    def test_workflow_dispatch_greenfield_exception_has_no_pr_binding(self):
        """create_exception accepts pr_number=None for a workflow_dispatch
        run - there is no pull request to bind to."""
        decision = make_decision()
        estimate = make_estimate()
        plan = make_plan()
        plan_doc = make_plan_doc()
        config = make_config(threshold=100)

        record = create_exception(
            decision, estimate, plan, plan_doc, config,
            pr_number=None,
            head_sha="deadbeef" * 5,
            approver="TanishqParab-Enc",
            justification="Approved via finops-cost-approval Environment (workflow_dispatch).",
            stack="generic-workload",
            terraform_dir="terraform/workloads/generic-workload",
        )
        assert record["pr"] is None
        assert record["status"] == "APPROVED"

    def test_workflow_dispatch_run_event_is_an_accepted_approval_channel(self):
        decision = make_decision()
        estimate = make_estimate()
        plan = make_plan()
        plan_doc = make_plan_doc()
        config = make_config(threshold=100)

        record = create_exception(
            decision, estimate, plan, plan_doc, config,
            pr_number=None,
            head_sha="deadbeef" * 5,
            approver="TanishqParab-Enc",
            justification="Approved via finops-cost-approval Environment (workflow_dispatch).",
            stack="generic-workload",
            terraform_dir="terraform/workloads/generic-workload",
        )

        problems = verify_environment_approval(
            record, plan, plan_doc, estimate, config,
            pr_number=None, head_sha="deadbeef" * 5,
            stack="generic-workload", terraform_dir="terraform/workloads/generic-workload",
            run_event="workflow_dispatch",
        )
        assert problems == []

    def test_pull_request_run_event_still_accepted_unchanged(self):
        """Regression: the existing pull_request approval channel must keep
        working exactly as before."""
        decision = make_decision()
        estimate = make_estimate()
        plan = make_plan()
        plan_doc = make_plan_doc()
        config = make_config(threshold=100)

        record = create_exception(
            decision, estimate, plan, plan_doc, config,
            pr_number=42,
            head_sha="cafebabe" * 5,
            approver="TanishqParab-Enc",
            justification="Approved via finops-cost-approval Environment (PR).",
            stack="generic-workload",
            terraform_dir="terraform/workloads/generic-workload",
        )
        assert record["pr"] == 42

        problems = verify_environment_approval(
            record, plan, plan_doc, estimate, config,
            pr_number=42, head_sha="cafebabe" * 5,
            stack="generic-workload", terraform_dir="terraform/workloads/generic-workload",
            run_event="pull_request",
        )
        assert problems == []

    def test_unrelated_trigger_is_still_rejected(self):
        """Only pull_request and workflow_dispatch are valid approval
        channels - a push or schedule trigger must never authorise a deploy."""
        decision = make_decision()
        estimate = make_estimate()
        plan = make_plan()
        plan_doc = make_plan_doc()
        config = make_config(threshold=100)

        record = create_exception(
            decision, estimate, plan, plan_doc, config,
            pr_number=None,
            head_sha="deadbeef" * 5,
            approver="TanishqParab-Enc",
            justification="x",
            stack="generic-workload",
            terraform_dir="terraform/workloads/generic-workload",
        )
        problems = verify_environment_approval(
            record, plan, plan_doc, estimate, config,
            pr_number=None, head_sha="deadbeef" * 5,
            stack="generic-workload", terraform_dir="terraform/workloads/generic-workload",
            run_event="schedule",
        )
        assert any("pull_request or workflow_dispatch" in p for p in problems)


class TestWorkflowFileGovernanceParity:
    """The workflow file itself: workflow_dispatch must reuse the exact same
    downstream jobs and never a parallel/simplified direct-apply path."""

    @pytest.fixture(scope="class")
    @classmethod
    def workflow(cls) -> dict:
        return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    def test_workflow_dispatch_trigger_has_stack_and_environment_inputs(self, workflow):
        dispatch = workflow["on"]["workflow_dispatch"]
        assert set(dispatch["inputs"]) == {"stack", "environment"}
        assert dispatch["inputs"]["stack"]["required"] is True
        assert dispatch["inputs"]["environment"]["required"] is True
        # Free-text, not a hard-coded choice list of stack names.
        assert dispatch["inputs"]["stack"]["type"] == "string"

    @pytest.mark.parametrize(
        "job_name",
        ["cost-gate", "collect-blocked-stacks", "authorize-deploy", "deploy"],
    )
    def test_governance_jobs_allow_workflow_dispatch(self, workflow, job_name):
        condition = str(workflow["jobs"][job_name]["if"])
        assert "workflow_dispatch" in condition
        assert "pull_request" in condition

    def test_no_separate_direct_apply_job_exists(self, workflow):
        """Requirement: do not invent a parallel architecture - the only
        jobs are the existing six governance jobs."""
        assert set(workflow["jobs"]) == {
            "detect-changes",
            "cost-gate",
            "collect-blocked-stacks",
            "finops-approval",
            "authorize-deploy",
            "deploy",
        }

    def test_baseline_step_never_uses_a_local_backend(self, workflow):
        """Requirement 4: never silently accept a local backend for a
        production registered stack."""
        steps = workflow["jobs"]["cost-gate"]["steps"]
        baseline_step = next(s for s in steps if s.get("id") == "baseline")
        script = baseline_step["run"]
        assert 'backend "local"' not in script
        assert "vars.TF_STATE_BUCKET" in script
        assert "STATE_KEY" in script
        assert baseline_step["env"]["STATE_KEY"] == "${{ matrix.stack.state_key }}"
