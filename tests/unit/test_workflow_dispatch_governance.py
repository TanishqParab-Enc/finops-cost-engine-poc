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
        assert set(dispatch["inputs"]) == {"cloud", "stack", "environment", "apply"}
        assert dispatch["inputs"]["stack"]["required"] is True
        assert dispatch["inputs"]["environment"]["required"] is True
        # Free-text, not a hard-coded choice list of stack names.
        assert dispatch["inputs"]["stack"]["type"] == "string"

    def test_dispatch_cloud_is_a_closed_choice_of_the_supported_clouds(self, workflow):
        """Greenfield picks the cloud in the UI, so the list must be closed -
        an unsupported cloud can never reach a credential exchange."""
        cloud = workflow["on"]["workflow_dispatch"]["inputs"]["cloud"]
        assert cloud["type"] == "choice"
        assert cloud["required"] is True
        assert {opt.lower() for opt in cloud["options"]} == {"aws", "azure", "gcp"}
        # AWS stays the default so the validated path is the zero-input one.
        assert str(cloud["default"]).lower() == "aws"

    def test_apply_input_is_an_opt_in_boolean(self, workflow):
        apply_input = workflow["on"]["workflow_dispatch"]["inputs"]["apply"]
        assert apply_input["type"] == "boolean"
        assert apply_input["default"] is False

    def test_apply_only_restricts_the_dispatch_path_and_never_the_pr_path(self, workflow):
        """`apply` may only subtract from what a dispatch run does; it must
        not appear as an alternative authorisation source, and must not be
        consulted for a pull_request."""
        condition = str(workflow["jobs"]["deploy"]["if"])
        assert "inputs.apply == true" in condition
        assert "github.event_name != 'workflow_dispatch' || inputs.apply == true" in condition
        # authorize-deploy remains the only authorisation source.
        assert "needs.authorize-deploy.result == 'success'" in condition
        for job in ("cost-gate", "collect-blocked-stacks", "authorize-deploy"):
            assert "inputs.apply" not in str(workflow["jobs"][job]["if"])

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


class TestRealRegistryResolvesTheDispatchedStack:
    """Runtime-path regression: the values the workflow actually feeds into
    `working-directory` and the S3 `-backend-config` come from the committed
    registry, so assert the committed registry itself, not a fixture."""

    @pytest.fixture(scope="class")
    @classmethod
    def registry(cls) -> dict:
        return load_stacks(REPO_ROOT / "config" / "finops-stacks.yml")

    def test_web_platform_resolves_to_its_own_workload_root(self, registry):
        assert registry["web-platform"].terraform_dir == "terraform/workloads/web-platform"

    def test_web_platform_dev_resolves_to_its_own_remote_state_key(self, registry):
        stack = registry["web-platform"]
        assert stack.environment == "dev"
        assert stack.state_key == "finops-poc/dev/web-platform/terraform.tfstate"

    def test_no_registered_stack_points_at_a_bare_terraform_root(self, registry):
        for stack in registry.values():
            assert stack.terraform_dir not in ("terraform", "terraform/", ".")
            assert stack.state_key, f"{stack.name} has no state_key"

    def test_dispatched_stack_is_never_resolved_from_a_cloud_name(self, registry):
        """`aws` is a registered STACK whose root happens to be terraform/aws.
        It must not be reachable as a cloud-name fallback for another stack:
        selecting web-platform must never yield the aws stack's root."""
        assert registry["web-platform"].terraform_dir != registry["aws"].terraform_dir
        assert registry["web-platform"].state_key != registry["aws"].state_key


class TestNoLegacyCloudDispatchPath:
    """Root-cause regression for the failed run on main, which used a legacy
    `cloud`-choice dispatch that planned terraform/aws over a local backend
    and produced only `aws_instance.app[0]`."""

    @pytest.fixture(scope="class")
    @classmethod
    def workflow(cls) -> dict:
        return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    @pytest.fixture(scope="class")
    @classmethod
    def raw(cls) -> str:
        return WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_dispatch_has_no_cloud_or_deploy_inputs(self, workflow):
        """`cloud` is now a legitimate GREENFIELD input, but it must be the
        only one added: a dispatch still must not carry its own deploy target,
        which would bypass the registry."""
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        for legacy in ("deploy", "deploy_environment"):
            assert legacy not in inputs

    def test_dispatch_cloud_is_validated_against_the_registry(self, workflow):
        """The UI selection is a request, not an authority. The registry must
        confirm it, and a mismatch must fail closed rather than be silently
        overridden with the registry's own value."""
        steps = workflow["jobs"]["detect-changes"]["steps"]
        detect = next(s for s in steps if s.get("id") == "detect")
        script = detect["run"]
        assert detect["env"]["DISPATCH_CLOUD"] == "${{ github.event.inputs.cloud }}"
        # validate_selection raises on a cloud/environment mismatch.
        assert "validate_selection" in script
        assert 'validate_selection(stack, cloud, environment)' in script
        assert "Stack selection rejected" in script

    def test_pull_request_never_takes_a_manual_cloud(self, workflow):
        """Brownfield resolves the cloud dynamically from the registry, so the
        PR branch must not consult the dispatch input at all."""
        steps = workflow["jobs"]["detect-changes"]["steps"]
        detect = next(s for s in steps if s.get("id") == "detect")
        script = detect["run"]
        pr_branch = script.split("BASE=", 1)[1]
        assert "DISPATCH_CLOUD" not in pr_branch
        # Unfiltered by cloud: every changed stack carries its own.
        assert "select_stacks(files)" in pr_branch

    def test_no_job_matrixes_over_cloud_names(self, raw):
        assert "matrix.cloud" not in raw
        assert "options: [aws, azure, gcp]" not in raw

    def test_cost_gate_matrix_is_the_resolved_stack_registry_json(self, workflow):
        matrix = workflow["jobs"]["cost-gate"]["strategy"]["matrix"]
        assert "stack" in matrix
        assert "needs.detect-changes.outputs.stacks" in str(matrix["stack"])

    def test_plan_steps_use_the_resolved_stack_directory(self, workflow):
        steps = workflow["jobs"]["cost-gate"]["steps"]
        dirs = [s.get("working-directory", "") for s in steps]
        assert "baseline/${{ matrix.stack.dir }}" in dirs
        assert "head/${{ matrix.stack.dir }}" in dirs
        # The only terraform/aws reference left must be explicitly guarded to
        # the `aws` stack itself - never a fallback for another stack.
        for step in steps:
            if "terraform/aws" in str(step.get("working-directory", "")):
                assert step.get("if") == "matrix.stack.name == 'aws'"

    def test_deploy_job_applies_the_resolved_stack_directory(self, workflow):
        steps = workflow["jobs"]["deploy"]["steps"]
        dirs = [s.get("working-directory", "") for s in steps]
        assert "${{ matrix.stack.dir }}" in dirs
        assert not any(d == "terraform/aws" for d in dirs)

    def test_deploy_backend_key_is_per_stack_and_per_environment(self, workflow):
        steps = workflow["jobs"]["deploy"]["steps"]
        init = next(
            s for s in steps
            if "terraform init" in str(s.get("run", "")) and "backend-config" in str(s.get("run", ""))
        )
        # The registry's own state_key - never a string rebuilt from the
        # environment, which could drift from the key the gate baselined.
        assert 'key=${{ matrix.stack.state_key }}' in init["run"]
        assert 'backend "local"' not in init["run"]

    def test_detect_changes_emits_state_key_on_both_trigger_paths(self, workflow):
        """Assert the BEHAVIOUR of the shared routing helper both branches use,
        rather than counting string literals in the workflow text."""
        from finops.stacks import load_stacks, stack_matrix_entry

        steps = workflow["jobs"]["detect-changes"]["steps"]
        detect = next(s for s in steps if s.get("id") == "detect")
        script = detect["run"]
        # Both branches build their matrix from the one helper.
        assert script.count("stack_matrix_entry") >= 2

        registry = load_stacks(REPO_ROOT / "config" / "finops-stacks.yml")
        for stack in registry.values():
            entry = stack_matrix_entry(stack)
            assert entry["state_key"] == stack.state_key
            assert entry["cloud"] == stack.cloud
            # GitHub renders a null expression as the literal "None".
            assert None not in entry.values()

    def test_state_keys_are_routed_per_cloud(self, workflow):
        """Azure/GCP live under their own prefix; existing AWS keys are frozen."""
        from finops.stacks import load_stacks, stack_matrix_entry

        registry = load_stacks(REPO_ROOT / "config" / "finops-stacks.yml")

        assert stack_matrix_entry(registry["azure-sandbox"])["state_key"] == (
            "finops-poc/dev/azure/sandbox/terraform.tfstate"
        )
        assert stack_matrix_entry(registry["gcp-sandbox"])["state_key"] == (
            "finops-poc/dev/gcp/sandbox/terraform.tfstate"
        )
        # Frozen AWS keys - these must never move.
        assert registry["web-platform"].state_key == "finops-poc/dev/web-platform/terraform.tfstate"
        assert registry["aws"].state_key == "finops-poc/dev/aws/terraform.tfstate"

        for stack in registry.values():
            if stack.cloud == "aws":
                assert "/azure/" not in stack.state_key
                assert "/gcp/" not in stack.state_key
            else:
                assert stack.state_key.startswith(f"finops-poc/dev/{stack.cloud}/")

    def test_dispatch_branch_hard_codes_no_stack_name(self, workflow):
        steps = workflow["jobs"]["detect-changes"]["steps"]
        detect = next(s for s in steps if s.get("id") == "detect")
        script = detect["run"]
        assert "web-platform" not in script
        assert 'DISPATCH_STACK' in script or "os.environ" in script


class TestSingleSharedPipeline:
    """Both triggers must enter ONE pipeline: one cost gate, one approval
    mechanism, one OIDC path, one apply. Never a parallel greenfield copy."""

    @pytest.fixture(scope="class")
    @classmethod
    def workflow(cls) -> dict:
        return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    def _jobs_with(self, workflow, predicate) -> list[str]:
        found = []
        for name, job in workflow["jobs"].items():
            for step in job.get("steps") or []:
                if predicate(step):
                    found.append(name)
                    break
        return found

    def test_exactly_one_job_runs_terraform_apply(self, workflow):
        appliers = self._jobs_with(
            workflow, lambda s: "terraform apply" in str(s.get("run", ""))
        )
        assert appliers == ["deploy"]

    def test_exactly_one_approval_environment_exists(self, workflow):
        gated = {
            name: job["environment"]
            for name, job in workflow["jobs"].items()
            if "environment" in job
        }
        approval = [n for n, e in gated.items() if "finops-cost-approval" in str(e)]
        assert approval == ["finops-approval"]

    def test_the_approval_environment_is_shared_by_both_triggers(self, workflow):
        """finops-approval is not conditioned on the event type, so a BLOCK
        from either trigger waits on the same Environment gate."""
        job = workflow["jobs"]["finops-approval"]
        assert job["environment"]["name"] == "finops-cost-approval"
        assert "workflow_dispatch" not in str(job.get("if", ""))
        assert "pull_request" not in str(job.get("if", ""))

    def test_exactly_one_oidc_role_assumption_path_for_deployment(self, workflow):
        """Multi-cloud replaces "exactly one credentials step" with a stronger
        rule: every credentials step must declare WHICH cloud it serves, and
        the two role families must never cross over.

        - AWS plan/deploy roles only when cloud == 'aws'
        - the state-only role only when cloud != 'aws'
        so no Azure/GCP path can hold AWS deployment rights, and the state-only
        role can never stand in as a target-cloud deployment role.
        """
        steps = workflow["jobs"]["deploy"]["steps"]
        creds = [s for s in steps if "configure-aws-credentials" in str(s.get("uses", ""))]
        assert creds, "the deploy job must assume a role via OIDC"

        aws_family = ("AWS_DEPLOY_ROLE_ARN", "AWS_PLAN_ROLE_ARN", "steps.role.outputs.arn")
        for step in creds:
            role = str(step["with"]["role-to-assume"])
            condition = str(step.get("if", ""))
            assert "role-to-assume" in step["with"]
            if "AWS_MULTICLOUD_STATE_ROLE_ARN" in role:
                assert condition == "matrix.stack.cloud != 'aws'", (
                    "the state-only role must be reachable only for non-AWS stacks"
                )
            else:
                assert any(token in role for token in aws_family), f"unknown role source: {role}"
                assert condition == "matrix.stack.cloud == 'aws'", (
                    "AWS plan/deploy roles must be reachable only for AWS stacks"
                )

        # Exactly one of each family - not an open-ended set of credential paths.
        state_only = [s for s in creds if "AWS_MULTICLOUD_STATE_ROLE_ARN" in str(s["with"]["role-to-assume"])]
        assert len(state_only) == 1
        assert len(creds) - len(state_only) == 1

        # No static credentials anywhere in the pipeline.
        raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "aws-access-key-id" not in raw
        assert "aws-secret-access-key" not in raw

    def test_target_cloud_auth_adapters_are_mutually_exclusive(self, workflow):
        """Azure and GCP deployment credentials are guarded by their own cloud,
        so one cloud's run can never authenticate to another's."""
        expected = {
            "./.github/actions/cloud-auth/azure": "matrix.stack.cloud == 'azure'",
            "./.github/actions/cloud-auth/gcp": "matrix.stack.cloud == 'gcp'",
        }
        for job_name in ("cost-gate", "deploy"):
            steps = workflow["jobs"][job_name]["steps"]
            seen = {}
            for step in steps:
                uses = str(step.get("uses", ""))
                for action, condition in expected.items():
                    if uses.endswith(action.lstrip(".")) or uses == action or uses == f"./head{action[1:]}":
                        seen[action] = str(step.get("if", ""))
            for action, condition in expected.items():
                assert action in seen, f"{job_name} is missing the {action} adapter"
                assert seen[action] == condition

    def test_no_cross_cloud_use_of_the_state_only_role(self, workflow):
        """The state-only role must never be handed to a cloud provider as a
        deployment identity, and AWS roles must never appear in a non-AWS step."""
        for job in workflow["jobs"].values():
            for step in job.get("steps") or []:
                rendered = str(step.get("with", "")) + str(step.get("env", ""))
                condition = str(step.get("if", ""))
                if "cloud == 'azure'" in condition or "cloud == 'gcp'" in condition:
                    assert "AWS_DEPLOY_ROLE_ARN" not in rendered
                    assert "AWS_PLAN_ROLE_ARN" not in rendered
                if "AWS_MULTICLOUD_STATE_ROLE_ARN" in rendered:
                    assert "cloud != 'aws'" in condition

    def test_oidc_role_is_not_branched_on_the_event_type(self, workflow):
        steps = workflow["jobs"]["deploy"]["steps"]
        creds = next(s for s in steps if "configure-aws-credentials" in str(s.get("uses", "")))
        role = str(creds["with"]["role-to-assume"])
        assert "workflow_dispatch" not in role
        assert "pull_request" not in role

    def test_proposed_cost_prices_the_complete_selected_stack(self, workflow):
        """The proposed plan is the whole selected stack's Terraform root -
        never a subset, a single resource, or another stack's root."""
        steps = workflow["jobs"]["cost-gate"]["steps"]
        proposed = next(
            s for s in steps
            if s.get("working-directory") == "head/${{ matrix.stack.dir }}"
            and "terraform plan" in str(s.get("run", ""))
        )
        assert "-target" not in proposed["run"]
        gate = next(s for s in steps if s.get("id") == "gate")
        assert "matrix.stack.usage_file" in str(gate.get("env", {}))

    def test_no_aws_instance_demo_resource_anywhere_in_the_pipeline(self, workflow):
        raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "aws_instance" not in raw

    def test_baseline_comes_from_remote_state_not_git_branch_presence(self, workflow):
        steps = workflow["jobs"]["cost-gate"]["steps"]
        baseline_checkout = next(
            s for s in steps
            if "checkout" in str(s.get("uses", "")) and s.get("with", {}).get("path") == "baseline"
        )
        # Same commit as head - the baseline is NOT the base branch.
        assert "ref" not in baseline_checkout["with"]
        baseline = next(s for s in steps if s.get("id") == "baseline")
        assert "terraform show -json > state.json" in baseline["run"]
        assert "state_json_to_plan_json" in baseline["run"]
        # The removed git-presence heuristic must not come back.
        raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "is_initial" not in raw
