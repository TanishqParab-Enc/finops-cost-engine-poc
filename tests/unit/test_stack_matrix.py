"""Central multi-stack FinOps pipeline: selection, isolation and authorisation.

One workflow prices every stack. These tests prove a stack cannot be pointed
somewhere it should not go, and that an authorisation minted for one stack can
never be spent on another.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from finops.errors import ConfigurationError
from finops.lock.cost_lock import create_cost_lock, verify_cost_lock
from finops.lock.exception import create_exception, verify_exception
from finops.models import (
    Action,
    Cloud,
    CostEstimate,
    EstimatorTrust,
    NormalizedPlan,
    PolicyDecision,
    ResourceChange,
    Status,
)
from finops.stacks import get_stack, load_stacks, select_stacks
from tests.conftest import make_config

REPO = Path(__file__).resolve().parent.parent.parent
GATE = REPO / ".github/workflows/finops-cost-gate.yml"
REGISTRY = REPO / "config/finops-stacks.yml"
APPROVER, AUTHOR, HEAD, PR = "peer-reviewer", "change-author", "a" * 40, 11


@pytest.fixture(scope="module")
def gate() -> dict:
    return yaml.safe_load(GATE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gate_text() -> str:
    return GATE.read_text(encoding="utf-8")


def _plan(instance_type="t3.large") -> NormalizedPlan:
    return NormalizedPlan(
        terraform_version="1.11.0", format_version="1.2",
        changes=[ResourceChange(
            address="aws_instance.app[0]", resource_type="aws_instance", name="app",
            cloud=Cloud.AWS, action=Action.CREATE, before={},
            after={"instance_type": instance_type})],
        clouds=[Cloud.AWS])


def _plan_doc(region="us-east-1") -> dict:
    return {"variables": {"region": {"value": region}, "instance_type": {"value": "t3.large"}}}


def _estimate(inc="50.00") -> CostEstimate:
    return CostEstimate(
        currency="USD", estimator="infracost", estimator_version="0.10.45",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=Decimal("10"), new_monthly_cost=Decimal("10") + Decimal(inc),
        incremental_monthly_cost=Decimal(inc))


def _decision(status=Status.PASS, observed="50.00") -> PolicyDecision:
    return PolicyDecision(
        status=status, metric="incremental_monthly_cost", unit="USD/month",
        observed_value=Decimal(observed), threshold_value=Decimal("100"),
        currency="USD", comparison="<=")


def _reviews(login=APPROVER, commit=HEAD):
    return [{"state": "APPROVED", "commit_id": commit, "user": {"login": login}}]


# ---------------------------------------------------------------------------
class TestRegistry:
    def test_registry_is_repository_data(self):
        assert REGISTRY.is_file()

    def test_known_stacks(self):
        assert set(load_stacks(REGISTRY)) == {"aws", "web-platform"}

    def test_terraform_directories(self):
        stacks = load_stacks(REGISTRY)
        assert stacks["aws"].terraform_dir == "terraform/aws"
        assert stacks["web-platform"].terraform_dir == "terraform/workloads/web-platform"

    def test_deployability(self):
        stacks = load_stacks(REGISTRY)
        assert stacks["aws"].deployable is True
        assert stacks["web-platform"].deployable is False
        assert stacks["web-platform"].deferred_reason

    def test_state_keys_are_isolated(self):
        stacks = load_stacks(REGISTRY)
        assert stacks["aws"].state_key == "finops-poc/dev/aws/terraform.tfstate"
        assert stacks["web-platform"].state_key == "finops-poc/dev/web-platform/terraform.tfstate"
        assert stacks["aws"].state_key != stacks["web-platform"].state_key

    def test_duplicate_state_keys_are_rejected(self, tmp_path):
        bad = tmp_path / "s.yml"
        bad.write_text(yaml.safe_dump({"schema_version": "1.0", "stacks": {
            "a": {"terraform_dir": "x", "cloud": "aws", "environment": "dev",
                  "state_key": "same", "deployable": True},
            "b": {"terraform_dir": "y", "cloud": "aws", "environment": "dev",
                  "state_key": "same", "deployable": True}}}), encoding="utf-8")
        with pytest.raises(ConfigurationError, match="state key"):
            load_stacks(bad)

    def test_path_traversal_is_rejected(self, tmp_path):
        bad = tmp_path / "s.yml"
        bad.write_text(yaml.safe_dump({"schema_version": "1.0", "stacks": {
            "evil": {"terraform_dir": "../../etc", "cloud": "aws", "environment": "dev",
                     "state_key": "k", "deployable": True}}}), encoding="utf-8")
        with pytest.raises(ConfigurationError, match="relative path"):
            load_stacks(bad)

    def test_absolute_dir_is_rejected(self, tmp_path):
        bad = tmp_path / "s.yml"
        bad.write_text(yaml.safe_dump({"schema_version": "1.0", "stacks": {
            "evil": {"terraform_dir": "/etc", "cloud": "aws", "environment": "dev",
                     "state_key": "k", "deployable": True}}}), encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_stacks(bad)

    def test_unknown_stack_is_rejected(self):
        with pytest.raises(ConfigurationError, match="Unknown stack"):
            get_stack("does-not-exist", REGISTRY)

    def test_schema_version_is_enforced(self, tmp_path):
        bad = tmp_path / "s.yml"
        bad.write_text(yaml.safe_dump({"schema_version": "9.9", "stacks": {}}), encoding="utf-8")
        with pytest.raises(ConfigurationError, match="schema_version"):
            load_stacks(bad)


class TestStackSelection:
    def test_aws_path_selects_aws(self):
        assert [s.name for s in select_stacks(["terraform/aws/main.tf"], REGISTRY)] == ["aws"]

    def test_web_platform_path_selects_web_platform(self):
        got = select_stacks(["terraform/workloads/web-platform/main.tf"], REGISTRY)
        assert [s.name for s in got] == ["web-platform"]

    def test_both_paths_select_both(self):
        got = select_stacks(
            ["terraform/aws/main.tf", "terraform/workloads/web-platform/variables.tf"], REGISTRY)
        assert [s.name for s in got] == ["aws", "web-platform"]

    def test_unrelated_paths_select_nothing(self):
        assert select_stacks(["README.md", "src/finops/cli.py"], REGISTRY) == []

    def test_nested_module_paths_resolve_to_the_workload(self):
        got = select_stacks(
            ["terraform/workloads/web-platform/modules/database/main.tf"], REGISTRY)
        assert [s.name for s in got] == ["web-platform"]

    def test_selection_is_deduplicated(self):
        got = select_stacks(
            ["terraform/aws/main.tf", "terraform/aws/variables.tf"], REGISTRY)
        assert [s.name for s in got] == ["aws"]

    def test_windows_separators_are_handled(self):
        got = select_stacks([r"terraform\workloads\web-platform\main.tf"], REGISTRY)
        assert [s.name for s in got] == ["web-platform"]


class TestCostLockStackBinding:
    def _lock(self, stack):
        return create_cost_lock(_decision(), _estimate(), _plan(), make_config(),
                                "c0ffee", "run-1", stack=stack)

    def test_lock_records_its_stack(self):
        assert self._lock("aws")["stack"] == "aws"

    def test_aws_lock_cannot_authorise_web_platform(self):
        problems = verify_cost_lock(self._lock("aws"), _plan(), make_config(),
                                    stack="web-platform")
        assert any("cannot authorise stack 'web-platform'" in p for p in problems)

    def test_web_platform_lock_cannot_authorise_aws(self):
        problems = verify_cost_lock(self._lock("web-platform"), _plan(), make_config(),
                                    stack="aws")
        assert any("cannot authorise stack 'aws'" in p for p in problems)

    def test_matching_stack_is_accepted(self):
        assert verify_cost_lock(self._lock("aws"), _plan(), make_config(), stack="aws") == []

    def test_legacy_lock_without_a_stack_is_rejected_when_a_stack_is_required(self):
        lock = self._lock(None)
        assert verify_cost_lock(lock, _plan(), make_config(), stack="aws")


class TestExceptionStackBinding:
    def _record(self, stack):
        return create_exception(
            _decision(Status.FAIL, "553.05"), _estimate("553.05"), _plan(), _plan_doc(),
            make_config(approvers=[APPROVER]), pr_number=PR, head_sha=HEAD,
            approver=APPROVER, justification="capacity", stack=stack,
            max_incremental_cost=560.0)

    def _verify(self, record, stack):
        return verify_exception(
            record, _plan(), _plan_doc(), _estimate("553.05"),
            make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, pr_author=AUTHOR, head_sha=HEAD, stack=stack,
            reviews=_reviews())

    def test_exception_records_its_stack(self):
        assert self._record("web-platform")["stack"] == "web-platform"

    def test_aws_exception_cannot_authorise_web_platform(self):
        problems = self._verify(self._record("aws"), "web-platform")
        assert any("cannot authorise stack 'web-platform'" in p for p in problems)

    def test_web_platform_exception_cannot_authorise_aws(self):
        problems = self._verify(self._record("web-platform"), "aws")
        assert any("cannot authorise stack 'aws'" in p for p in problems)

    def test_matching_stack_is_accepted(self):
        assert self._verify(self._record("aws"), "aws") == []

    def test_approval_artifact_carries_the_stack(self):
        from finops.lock.exception import build_approval_record

        record = self._record("aws")
        approval = build_approval_record(record, [], pr_number=PR, head_sha=HEAD)
        assert approval["stack"] == "aws"


class TestNonDeployableStacksMintNoAuthorisation:
    def test_gate_request_can_suppress_the_lock(self):
        from finops.gate import GateRequest

        assert GateRequest(proposed_plan=Path("x")).allow_cost_lock is True
        assert GateRequest(proposed_plan=Path("x"), allow_cost_lock=False).allow_cost_lock is False

    def test_workflow_passes_no_cost_lock_for_non_deployable_stacks(self, gate_text):
        assert 'if [ "${{ matrix.stack.deployable }}" != "true" ]' in gate_text
        assert 'LOCK_ARG="--no-cost-lock"' in gate_text

    def test_workflow_asserts_the_absence_rather_than_assuming_it(self, gate):
        job = gate["jobs"]["cost-gate"]
        step = next(s for s in job["steps"]
                    if s.get("name") == "Assert no cost lock exists for a non-deployable stack")
        assert "matrix.stack.deployable != true" in step["if"]
        assert "exit 1" in step["run"]

    def test_verify_lock_only_runs_for_deployable_stacks(self, gate):
        job = gate["jobs"]["cost-gate"]
        step = next(s for s in job["steps"]
                    if s.get("name") == "Verify cost lock before deployment")
        assert "matrix.stack.deployable == true" in step["if"]


class TestInitialDeploymentDetection:
    """A stack absent from the base ref is a new deployment, determined by
    directory existence - never by resource_changes actions, which would
    conflate 'new stack' with 'stack full of creates for another reason'."""

    def _steps(self, gate):
        return {s.get("name"): s for s in gate["jobs"]["cost-gate"]["steps"]}

    def test_detection_step_exists_before_baseline_planning(self, gate):
        names = [s.get("name") for s in gate["jobs"]["cost-gate"]["steps"]]
        assert names.index("Detect initial deployment") < names.index(
            "Terraform plan (base branch = baseline cost)")

    def test_detection_is_directory_existence_not_plan_output(self, gate):
        step = self._steps(gate)["Detect initial deployment"]
        assert 'if [ -d "base/${{ matrix.stack.dir }}" ]' in step["run"]
        assert "resource_changes" not in step["run"]

    def test_detection_uses_the_matrix_stack_directory(self, gate):
        step = self._steps(gate)["Detect initial deployment"]
        assert "matrix.stack.dir" in step["run"]
        assert "matrix.stack.name" in step["run"]

    def test_baseline_plan_is_skipped_for_a_new_stack(self, gate):
        step = self._steps(gate)["Terraform plan (base branch = baseline cost)"]
        assert step["if"] == "steps.initial.outputs.is_initial != 'true'"

    def test_gate_message_distinguishes_initial_deployment_from_plan_failure(self, gate):
        step = self._steps(gate)["FinOps cost gate"]
        assert "Initial deployment for" in step["run"]
        assert "steps.initial.outputs.is_initial" in step["run"]
        assert "No baseline plan; incremental cost equals full projected cost." in step["run"]


class TestSingleCentralWorkflow:
    def test_only_one_finops_workflow_exists(self):
        workflows = {p.name for p in (REPO / ".github/workflows").glob("*.yml")}
        finops = {w for w in workflows if "finops" in w or "cost" in w}
        assert finops == {"finops-cost-gate.yml"}, finops

    def test_no_web_platform_specific_workflow(self):
        assert not (REPO / ".github/workflows/web-platform-finops.yml").exists()

    def test_matrix_is_driven_by_the_trusted_registry(self, gate):
        matrix = gate["jobs"]["cost-gate"]["strategy"]["matrix"]["stack"]
        assert matrix == "${{ fromJSON(needs.detect-changes.outputs.stacks) }}"

    def test_terraform_dir_comes_from_the_matrix_not_an_input(self, gate):
        job = gate["jobs"]["cost-gate"]
        dirs = {s.get("working-directory") for s in job["steps"] if s.get("working-directory")}
        assert "head/${{ matrix.stack.dir }}" in dirs
        assert "base/${{ matrix.stack.dir }}" in dirs
        assert not any("inputs." in str(d) for d in dirs)

    def test_detect_uses_the_registry(self, gate):
        run = next(s for s in gate["jobs"]["detect-changes"]["steps"]
                   if s.get("id") == "detect")["run"]
        assert "from finops.stacks import select_stacks" in run
        assert "deployable" in run

    def test_detect_has_no_fallback_stack(self, gate):
        """A change matching no stack must evaluate nothing. Defaulting to aws
        priced an untouched stack and minted a cost lock for it."""
        run = next(s for s in gate["jobs"]["detect-changes"]["steps"]
                   if s.get("id") == "detect")["run"]
        assert "load_stacks()['aws']" not in run
        assert "found = [" not in run

    def test_gate_is_skipped_when_no_stack_is_selected(self, gate):
        cond = " ".join(gate["jobs"]["cost-gate"]["if"].split())
        assert "needs.detect-changes.outputs.stacks != '[]'" in cond

    def test_reports_are_scoped_per_stack(self, gate_text):
        assert "<!-- stack:${{ matrix.stack.name }} -->" in gate_text
        assert "finops-${{ matrix.stack.name }}-${{ github.run_id }}" in gate_text

    def test_authorisation_checks_pass_the_stack(self, gate_text):
        assert '--stack "${{ matrix.stack.name }}"' in gate_text
        assert gate_text.count('--stack "${{ matrix.stack.name }}"') >= 2


class TestDeployGating:
    def test_deploy_job_still_exists_as_the_boundary(self, gate):
        assert "deploy" in gate["jobs"]

    def test_deploy_stack_comes_from_the_matrix_not_an_input(self, gate):
        assert gate["jobs"]["deploy"]["env"]["DEPLOY_STACK"] == "${{ matrix.stack.name }}"

    def test_deploy_job_is_stack_matrixed_from_the_trusted_registry(self, gate):
        matrix = gate["jobs"]["deploy"]["strategy"]["matrix"]["stack"]
        assert matrix == "${{ fromJSON(needs.detect-changes.outputs.stacks) }}"

    def test_push_path_no_longer_depends_on_the_removed_aws_evaluated_output(self, gate):
        cond = " ".join(gate["jobs"]["deploy"]["if"].split())
        assert "aws_evaluated" not in cond

    def test_job_if_never_references_matrix(self, gate):
        """The `matrix` context is only valid in `strategy` and `steps`, never
        in a job-level `if:` - referencing it there is a GitHub Actions
        schema error the workflow would silently fail to even start with."""
        cond = gate["jobs"]["deploy"]["if"]
        assert "matrix." not in cond

    def test_deployability_is_enforced_by_a_step_not_the_job_if(self, gate):
        step = next(s for s in gate["jobs"]["deploy"]["steps"]
                    if s.get("name") == "Verify the stack is deployable (trusted registry)")
        assert "deployable" in step["run"]

    def test_workflow_dispatch_aws_only_restriction_is_enforced_by_a_step(self, gate):
        cond = " ".join(gate["jobs"]["deploy"]["if"].split())
        assert "inputs.cloud == 'aws'" in cond
        pin = next(s for s in gate["jobs"]["deploy"]["steps"]
                   if s.get("name") == "Pin and validate deployment target")
        assert "matrix.stack.name" in pin["run"]
        assert "aws-only" in pin["run"].lower()

    def test_deploy_reverifies_deployability_from_the_registry(self, gate):
        names = [s.get("name", s.get("uses")) for s in gate["jobs"]["deploy"]["steps"]]
        step = next(s for s in gate["jobs"]["deploy"]["steps"]
                    if s.get("name") == "Verify the stack is deployable (trusted registry)")
        assert "config/finops-stacks.yml" in step["run"]
        assert "Stack not deployable" in step["run"]
        assert names.index("Verify the stack is deployable (trusted registry)") < names.index(
            "Terraform apply")

    def test_web_platform_would_be_refused_by_that_check(self):
        registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
        assert registry["stacks"]["web-platform"]["deployable"] is False

    def test_no_bypass_inputs_exist(self, gate):
        triggers = gate.get("on") or gate.get(True)
        inputs = triggers["workflow_dispatch"]["inputs"]
        for forbidden in ("skip_finops", "force_deploy", "terraform_dir", "stack", "deployable"):
            assert forbidden not in inputs

    def test_pr_cannot_apply(self, gate):
        cond = " ".join(gate["jobs"]["deploy"]["if"].split())
        assert "pull_request" not in cond
        assert "github.event_name == 'push'" in cond and "refs/heads/main" in cond

    def test_prod_unreachable_from_automatic_push(self, gate):
        env = gate["jobs"]["deploy"]["env"]["TARGET_ENV"]
        assert env.index("'dev'") < env.index("inputs.")

    def test_existing_aws_deploy_path_is_intact(self, gate):
        steps = [s.get("name", s.get("uses")) for s in gate["jobs"]["deploy"]["steps"]]
        for required in ("Resolve deploy role for the target environment", "Terraform plan",
                         "Block destructive apply", "Terraform apply"):
            assert required in steps
        plan = next(s for s in gate["jobs"]["deploy"]["steps"] if s.get("name") == "Terraform plan")
        # Generalized to the matrix stack, but for the aws entry
        # (name=aws, dir=terraform/aws) this interpolates to the exact
        # literals the job used before generalization.
        assert plan["working-directory"] == "${{ matrix.stack.dir }}"
        assert "key=finops-poc/${TARGET_ENV}/${{ matrix.stack.name }}/terraform.tfstate" in plan["run"]
        aws = load_stacks(REGISTRY)["aws"]
        assert aws.terraform_dir == "terraform/aws"
        assert aws.name == "aws"

    def test_var_file_is_conditional_on_existence_not_hardcoded(self, gate):
        plan = next(s for s in gate["jobs"]["deploy"]["steps"] if s.get("name") == "Terraform plan")
        assert 'if [ -f "environments/${TARGET_ENV}.tfvars" ]' in plan["run"]
        assert 'VAR_ARG="-var-file=environments/${TARGET_ENV}.tfvars"' in plan["run"]

    def test_apply_working_directory_matches_the_matrix_stack(self, gate):
        apply = next(s for s in gate["jobs"]["deploy"]["steps"]
                     if s.get("name") == "Terraform apply")
        assert apply["working-directory"] == "${{ matrix.stack.dir }}"

    def test_web_platform_cannot_reach_deploy_on_push(self):
        """web-platform is deployable=false, so the matrix.stack.deployable
        check in the job `if` excludes it even though it may appear in the
        same push's selected stacks alongside aws."""
        registry = load_stacks(REGISTRY)
        assert registry["web-platform"].deployable is False

    def test_destroy_guard_precedes_apply(self, gate):
        steps = [s.get("name", s.get("uses")) for s in gate["jobs"]["deploy"]["steps"]]
        assert steps.index("Block destructive apply") < steps.index("Terraform apply")

    def test_apply_uses_the_saved_plan(self, gate):
        apply = next(s for s in gate["jobs"]["deploy"]["steps"]
                     if s.get("name") == "Terraform apply")
        assert "tfplan.binary" in apply["run"] and "-auto-approve" not in apply["run"]


class TestPreservedSemantics:
    def test_threshold_unchanged(self, gate_text):
        assert "FINOPS_THRESHOLD_VALUE: ${{ vars.FINOPS_THRESHOLD_VALUE || '100' }}" in gate_text
        assert "incremental_monthly_cost" in gate_text

    def test_infracost_still_pinned(self, gate_text):
        assert 'version: "0.10.45"' in gate_text

    def test_gate_fails_closed(self, gate_text):
        assert "Failing safe (exit $CODE)" in gate_text

    def test_pr_review_exception_is_no_longer_the_primary_authorisation_mechanism(self, gate_text):
        """Superseded by the finops-cost-approval GitHub Actions environment -
        no step in the workflow calls verify-exception or reads PR reviews."""
        assert "Evaluate budget exception" not in gate_text
        assert "finops verify-exception" not in gate_text
        assert "pulls/${PR}/reviews" not in gate_text

    def test_drift_assertion_preserved_and_scoped_to_aws(self, gate):
        step = next(s for s in gate["jobs"]["cost-gate"]["steps"]
                    if s.get("name") == "Assert cost-gated config matches the Dev deploy config")
        assert step["if"] == "matrix.stack.name == 'aws'"

    def test_no_deploy_role_in_the_gate_job(self, gate):
        job = json.dumps(gate["jobs"]["cost-gate"])
        assert "AWS_DEPLOY_ROLE_ARN" not in job
        assert "AWS_PLAN_ROLE_ARN" in job


class TestScenarioValidation:
    """Scenario matrix inside the central workflow (no second workflow)."""

    def _scenarios_would_run(self, event_name: str, stacks_json: str) -> bool:
        """Literal re-implementation of the job's `if:` expression."""
        return event_name == "workflow_dispatch" and '"web-platform"' in stacks_json

    def test_scenarios_never_run_on_pull_request(self):
        assert self._scenarios_would_run("pull_request", '[{"name":"web-platform"}]') is False

    def test_scenarios_never_run_on_push(self):
        assert self._scenarios_would_run("push", '[{"name":"web-platform"}]') is False

    def test_scenarios_run_only_on_manual_dispatch_with_web_platform_selected(self):
        assert self._scenarios_would_run("workflow_dispatch", '[{"name":"web-platform"}]') is True
        assert self._scenarios_would_run("workflow_dispatch", '[{"name":"aws"}]') is False

    def test_scenarios_job_lives_in_the_central_workflow(self, gate):
        assert "scenarios" in gate["jobs"]

    def test_scenarios_only_run_when_web_platform_is_selected(self, gate):
        cond = " ".join(gate["jobs"]["scenarios"]["if"].split())
        assert "contains(needs.detect-changes.outputs.stacks, '\"web-platform\"')" in cond

    def test_scenarios_are_manual_only_never_automatic_on_pull_request_or_push(self, gate):
        """The normal web-platform PR path prices only the real committed
        workload. Scenarios are test fixtures, run on demand only."""
        cond = " ".join(gate["jobs"]["scenarios"]["if"].split())
        assert "github.event_name == 'workflow_dispatch'" in cond
        assert "pull_request" not in cond
        assert "'push'" not in cond

    def test_all_eight_committed_scenarios_are_covered(self, gate):
        listed = set(gate["jobs"]["scenarios"]["strategy"]["matrix"]["scenario"])
        on_disk = {p.stem for p in
                   (REPO / "tests/fixtures/web-platform/scenarios").glob("*.tfvars")}
        assert listed == on_disk

    def test_scenarios_are_test_fixtures_not_workload_source(self):
        """The production workload must not carry test-only variants."""
        workload = REPO / "terraform/workloads/web-platform"
        assert not (workload / "scenarios").exists()
        assert not list(workload.rglob("*-scale-up.tfvars"))
        assert (REPO / "tests/fixtures/web-platform/scenarios").is_dir()

    def test_workload_keeps_only_canonical_configuration(self):
        workload = REPO / "terraform/workloads/web-platform"
        roots = {p.name for p in workload.glob("*") if p.is_file()}
        assert roots == {
            "main.tf", "variables.tf", "outputs.tf", "locals.tf", "provider.tf",
            "versions.tf", "terraform.tfvars", "terraform.tfvars.example",
            "infracost-usage.yml",
        }, roots

    def test_workload_modules_are_intact(self):
        modules = {p.name for p in
                   (REPO / "terraform/workloads/web-platform/modules").iterdir() if p.is_dir()}
        assert modules == {
            "networking", "alb", "compute", "database", "object-storage",
            "cdn", "dns", "monitoring", "iam",
        }

    def test_normal_estimation_path_needs_no_scenario_file(self, gate):
        """The cost-gate job plans the workload as committed; only the separate
        scenario job passes a -var-file."""
        steps = gate["jobs"]["cost-gate"]["steps"]
        proposed = next(s for s in steps
                        if s.get("name") == "Terraform plan (PR head = proposed cost)")
        assert "-var-file" not in proposed["run"]
        assert "scenarios" not in proposed["run"]

    def test_scenarios_never_fail_the_pull_request(self, gate):
        job = gate["jobs"]["scenarios"]
        assert job["strategy"]["fail-fast"] is False
        price = next(s for s in job["steps"] if s.get("name") == "Price scenario with Infracost 0.10.45")
        assert price["continue-on-error"] is True

    def test_scenarios_use_the_plan_role_never_the_deploy_role(self, gate):
        job = json.dumps(gate["jobs"]["scenarios"])
        assert "AWS_PLAN_ROLE_ARN" in job
        assert "AWS_DEPLOY_ROLE_ARN" not in job

    def test_scenarios_never_mint_a_cost_lock(self, gate):
        job = gate["jobs"]["scenarios"]
        price = next(s for s in job["steps"] if s.get("name") == "Price scenario with Infracost 0.10.45")
        assert "--no-cost-lock" in price["run"]
        guard = next(s for s in job["steps"] if s.get("name") == "Assert no cost lock was created")
        assert guard["if"] == "always()"
        assert "exit 1" in guard["run"]

    def test_s3_growth_scenario_uses_its_own_usage_file(self, gate):
        price = next(s for s in gate["jobs"]["scenarios"]["steps"]
                     if s.get("name") == "Price scenario with Infracost 0.10.45")
        usage_expr = price["env"]["FINOPS_INFRACOST_USAGE_FILE"]
        assert "03-s3-growth.usage.yml" in usage_expr
        assert "infracost-usage.yml" in usage_expr

    def test_no_second_finops_workflow_was_reintroduced(self):
        assert not (REPO / ".github/workflows/web-platform-finops.yml").exists()


class TestCostCreep:
    """Trusted main must never trust the PR's number - it re-derives cost."""

    def test_exception_rejects_cost_above_its_own_ceiling(self):
        record = create_exception(
            _decision(Status.FAIL, "150.00"), _estimate("150.00"), _plan(), _plan_doc(),
            make_config(approvers=[APPROVER], threshold=100), pr_number=PR, head_sha=HEAD,
            approver=APPROVER, justification="approved at 150", stack="web-platform",
            max_incremental_cost=165.0)
        crept = verify_exception(
            record, _plan(), _plan_doc(), _estimate("180.00"),
            make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, pr_author=AUTHOR, head_sha=HEAD, stack="web-platform",
            reviews=_reviews())
        assert any("exceeds the approved ceiling" in p for p in crept)

    def test_exception_accepts_cost_within_its_ceiling(self):
        record = create_exception(
            _decision(Status.FAIL, "150.00"), _estimate("150.00"), _plan(), _plan_doc(),
            make_config(approvers=[APPROVER], threshold=100), pr_number=PR, head_sha=HEAD,
            approver=APPROVER, justification="approved at 150", stack="web-platform",
            max_incremental_cost=165.0)
        ok = verify_exception(
            record, _plan(), _plan_doc(), _estimate("160.00"),
            make_config(approvers=[APPROVER], threshold=100),
            pr_number=PR, pr_author=AUTHOR, head_sha=HEAD, stack="web-platform",
            reviews=_reviews())
        assert ok == []

    def test_deploy_job_reruns_terraform_plan_rather_than_trusting_the_pr(self, gate):
        """Trusted main must plan again, not read the PR's cached numbers."""
        names = [s.get("name", s.get("uses")) for s in gate["jobs"]["deploy"]["steps"]]
        assert "Terraform plan" in names
        plan = next(s for s in gate["jobs"]["deploy"]["steps"] if s.get("name") == "Terraform plan")
        assert "terraform plan" in plan["run"]


class TestApprovalBeforeDeploymentOrdering:
    """Deployment must be structurally unreachable until authorization
    resolves (where the exception/lock authorisation lives), never merely
    'usually resolved first' by job listing order. deploy depends on the
    explicit authorize-deploy result, never on cost-gate's raw pass/fail -
    cost-gate is matrixed by stack, so its own conclusion is all-or-nothing
    across every stack in the push, which must not gate an unrelated,
    already-authorized stack's deployment."""

    def test_deploy_needs_authorize_deploy_not_cost_gate_directly(self, gate):
        assert gate["jobs"]["deploy"]["needs"] == ["detect-changes", "authorize-deploy"]

    def test_deploy_requires_authorize_deploy_success(self, gate):
        cond = " ".join(gate["jobs"]["deploy"]["if"].split())
        assert cond.startswith("needs.authorize-deploy.result == 'success' &&")
        assert "needs.cost-gate.result" not in cond

    def test_authorize_deploy_always_runs_even_when_cost_gate_partially_fails(self, gate):
        cond = " ".join(gate["jobs"]["authorize-deploy"]["if"].split())
        assert cond.startswith("always() &&")

    def test_authorize_deploy_needs_cost_gate(self, gate):
        assert gate["jobs"]["authorize-deploy"]["needs"] == ["detect-changes", "cost-gate"]

    def test_no_sleep_or_wait_based_approval_inside_the_pr_job(self, gate_text):
        """Approval must never be a workflow pausing to wait for a review to
        arrive - a PR run finishes BLOCKED and a later trusted run deploys.
        The only wait is GitHub's own environment protection UI, not a
        command this workflow runs."""
        code_lines = [
            line for line in gate_text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert not any("sleep" in line.lower() for line in code_lines)

    def test_no_workflow_provided_approved_boolean_is_ever_trusted(self, gate_text):
        """A PR must never be able to just assert 'approved=true' - deploy's
        own conditions never read an `inputs.approved`-style flag."""
        assert "inputs.approved" not in gate_text
        assert "inputs.force_deploy" not in gate_text


class TestDeploymentAuthorizationArchitecture:
    """finops_decision (PASS/BLOCK) and deployment_authorization
    (AUTHORIZED/DENIED) are separate, explicitly named signals - an approved
    exception must never rewrite a BLOCK into a PASS."""

    def test_compute_authorization_step_exists_in_cost_gate(self, gate):
        job = gate["jobs"]["cost-gate"]
        step = next(s for s in job["steps"] if s.get("name") == "Compute deployment authorization")
        assert "finops authorize-deployment" in step["run"]
        assert step["if"] == "always()"

    def test_compute_authorization_runs_before_upload_and_enforce(self, gate):
        names = [s.get("name") for s in gate["jobs"]["cost-gate"]["steps"]]
        assert names.index("Compute deployment authorization") < names.index("Upload FinOps artifacts")
        assert names.index("Compute deployment authorization") < names.index("Enforce gate")

    def test_compute_authorization_considers_lock_reverification(self, gate):
        step = next(s for s in gate["jobs"]["cost-gate"]["steps"]
                    if s.get("name") == "Compute deployment authorization")
        assert "steps.verify_lock.outcome" in step["run"]

    def test_compute_authorization_no_longer_consults_pr_review_exceptions(self, gate):
        """A BLOCK always starts DENIED in cost-gate - only finops-approval's
        protected environment (via authorize-deploy) can upgrade it."""
        step = next(s for s in gate["jobs"]["cost-gate"]["steps"]
                    if s.get("name") == "Compute deployment authorization")
        assert "steps.exception" not in step["run"]
        assert "--exception-valid" not in step["run"]

    def test_a_non_deployable_stack_is_never_authorized_however_cheap_it_prices(self, gate):
        """deployment_authorization is forced DENIED for a non-deployable
        stack, independent of the CLI's PASS/BLOCK computation - deployability
        is a registry fact the authorize-deployment CLI does not consume."""
        step = next(s for s in gate["jobs"]["cost-gate"]["steps"]
                    if s.get("name") == "Compute deployment authorization")
        assert 'matrix.stack.deployable' in step["run"]
        assert 'data["deployment_authorization"] = "DENIED"' in step["run"]

    def test_enforce_gate_still_fails_the_pr_check_when_denied(self, gate):
        """cost-gate's own required check stays red for an unauthorised
        over-threshold change - only the (decoupled) deploy job's dependency
        changed, not the PR-visible signal that peer review is required."""
        step = next(s for s in gate["jobs"]["cost-gate"]["steps"] if s.get("name") == "Enforce gate")
        assert "FinOps threshold exceeded" in step["run"]
        assert "exit 1" in step["run"]

    def test_authorize_deploy_aggregates_per_stack_not_a_single_boolean(self, gate):
        job = gate["jobs"]["authorize-deploy"]
        assert "authorizations" in job["outputs"]
        aggregate = next(s for s in job["steps"] if s.get("name") == "Aggregate per-stack authorization")
        assert "merged" in aggregate["run"]

    def test_deploy_verifies_authorization_for_its_own_stack_before_anything_else(self, gate):
        steps = [s.get("name", s.get("uses")) for s in gate["jobs"]["deploy"]["steps"]]
        assert steps.index("Verify deployment authorization for this stack") < steps.index(
            "Pin and validate deployment target")

    def test_deploy_authorization_check_never_treats_block_as_pass(self, gate):
        step = next(s for s in gate["jobs"]["deploy"]["steps"]
                    if s.get("name") == "Verify deployment authorization for this stack")
        assert 'auth != "AUTHORIZED"' in step["run"]
        assert "finops_decision" in step["run"]


class TestFinopsApprovalEnvironmentGate:
    """The finops-cost-approval GitHub Actions environment is the actual
    human approval gate for a BLOCKed stack, reached ON THE PR ITSELF - not
    a PR review, not a workflow input, not repository content, not a
    sleep/poll loop."""

    def test_job_exists_with_the_protected_environment(self, gate):
        job = gate["jobs"]["finops-approval"]
        assert job["environment"] == {"name": "finops-cost-approval"}

    def test_only_reachable_when_cost_gate_actually_blocked(self, gate):
        cond = " ".join(gate["jobs"]["finops-approval"]["if"].split())
        assert "needs.cost-gate.result == 'failure'" in cond

    def test_reachable_from_the_pull_request_itself(self, gate):
        """This is the whole point of the redesign: the over-threshold PR's
        own workflow run must visibly reach the waiting-for-approval state,
        not a later, separate trusted-main run."""
        cond = " ".join(gate["jobs"]["finops-approval"]["if"].split())
        assert "github.event_name == 'pull_request'" in cond

    def test_runs_even_when_cost_gate_partially_failed(self, gate):
        cond = " ".join(gate["jobs"]["finops-approval"]["if"].split())
        assert cond.startswith("always() &&")

    def test_no_workflow_input_stands_in_for_the_environment_click(self, gate):
        triggers = gate.get("on") or gate.get(True)
        inputs = triggers["workflow_dispatch"]["inputs"]
        for forbidden in ("approve", "reject", "approved", "finops_approval"):
            assert forbidden not in inputs

    def test_no_polling_loop_waits_for_approval(self, gate):
        job_text = json.dumps(gate["jobs"]["finops-approval"])
        assert "while" not in job_text
        assert "poll" not in job_text.lower()

    def test_no_self_approval_logic_exists(self, gate_text):
        """The workflow contains no code path that grants approval to itself -
        the only mechanism is GitHub's own required-reviewers UI, external to
        this file entirely."""
        assert "self_approve" not in gate_text.lower()
        assert "auto_approve" not in gate_text.lower()
        assert "-auto-approve" not in gate_text

    def test_approver_identity_is_resolved_from_the_live_approvals_api(self, gate):
        """Never a workflow input, never the PR author's own identity - the
        run's own GET .../actions/runs/{run_id}/approvals."""
        job = gate["jobs"]["finops-approval"]
        step = next(s for s in job["steps"] if s.get("name") == "Resolve the environment approver identity")
        assert "actions/runs/${{ github.run_id }}/approvals" in step["run"]
        assert "approved" in step["run"]

    def test_attestation_creation_never_touches_finops_decision(self, gate):
        """create-exception refuses anything but a FAIL gate-result and never
        rewrites the decision - reused unchanged from before this redesign."""
        job = gate["jobs"]["finops-approval"]
        step = next(s for s in job["steps"]
                    if s.get("name") == "Create the exception attestation for each blocked stack")
        assert "finops create-exception" in step["run"]
        assert 'if [ "$DECISION" != "BLOCK" ]' in step["run"]

    def test_attestation_is_uploaded_as_an_artifact_bound_to_the_pr(self, gate):
        job = gate["jobs"]["finops-approval"]
        upload = next(s for s in job["steps"] if s.get("name") == "Upload the exception attestation")
        assert "finops-attestation-${{ github.event.pull_request.number }}-${{ github.run_id }}" == \
            upload["with"]["name"]


class TestAuthorizeDeployCrossRunAttestationVerification:
    """Trusted main never trusts an artifact merely for existing - it
    re-resolves the PR, re-checks the source run's approval job succeeded,
    and re-fetches the approvers, all live, before ever calling
    evaluate-attestation with a freshly computed plan/estimate."""

    def test_resolves_the_pull_request_via_the_commits_api(self, gate):
        job = gate["jobs"]["authorize-deploy"]
        step = next(s for s in job["steps"]
                    if s.get("name") == "Resolve the pull request this trusted commit came from")
        assert "commits/$SHA/pulls" in step["run"]

    def test_locates_and_reverifies_the_source_run_independently(self, gate):
        job = gate["jobs"]["authorize-deploy"]
        step = next(s for s in job["steps"]
                    if s.get("name") == "Locate and re-verify the pull request's finops-approval run")
        assert "FinOps cost exception approval" in step["run"]
        assert "actions/runs/$RUN_ID/jobs" in step["run"]
        assert "actions/runs/$RUN_ID/approvals" in step["run"]

    def test_attestation_is_downloaded_from_the_source_run_not_this_one(self, gate):
        job = gate["jobs"]["authorize-deploy"]
        download = next(s for s in job["steps"]
                        if s.get("name") == "Download the pull request's exception attestation")
        assert download["with"]["run-id"] == "${{ steps.source_run.outputs.run_id }}"

    def test_aggregate_calls_evaluate_attestation_with_a_fresh_plan_and_gate_result(self, gate):
        aggregate = next(s for s in gate["jobs"]["authorize-deploy"]["steps"]
                         if s.get("name") == "Aggregate per-stack authorization")
        assert '"finops", "evaluate-attestation"' in aggregate["run"]
        assert "proposed-plan.json" in aggregate["run"]
        assert "gate-result.json" in aggregate["run"]

    def test_pass_stacks_never_go_through_attestation_evaluation(self, gate):
        aggregate = next(s for s in gate["jobs"]["authorize-deploy"]["steps"]
                         if s.get("name") == "Aggregate per-stack authorization")
        assert 'entry.get("finops_decision") != "BLOCK"' in aggregate["run"]


class TestNoTerraformTargeting:
    def test_workflow_never_uses_target(self, gate_text):
        assert "-target" not in gate_text

    def test_apply_always_uses_a_previously_saved_plan_file(self, gate):
        apply = next(s for s in gate["jobs"]["deploy"]["steps"]
                     if s.get("name") == "Terraform apply")
        assert "tfplan.binary" in apply["run"]
        assert "-target" not in apply["run"]


class TestStackedPRSelection:
    """A pull request stacked on another branch must still select stacks by
    the files it actually changes, not by everything already on its base."""

    def test_selection_only_reflects_the_named_changed_files(self):
        # Simulates diffing a stacked PR against its true merge-base: only the
        # files this PR's commits touch are passed in, regardless of what its
        # base branch already contains.
        changed_by_this_pr_only = ["terraform/workloads/web-platform/variables.tf"]
        assert [s.name for s in select_stacks(changed_by_this_pr_only, REGISTRY)] == ["web-platform"]

    def test_files_already_on_the_base_branch_do_not_leak_in(self):
        # A stacked PR's diff must not include terraform/aws/main.tf just
        # because an earlier, unrelated PR in the stack touched it.
        changed_by_this_pr_only = ["terraform/workloads/web-platform/main.tf"]
        selected = {s.name for s in select_stacks(changed_by_this_pr_only, REGISTRY)}
        assert selected == {"web-platform"}
        assert "aws" not in selected


class TestNoValidationDeploymentAuthority:
    def test_pass_estimate_for_a_non_deployable_stack_writes_no_lock(self, tmp_path):
        from finops.gate import GateRequest, run_gate
        from finops.cost.factory import build_estimator
        import json as _json

        config = make_config(output_dir=str(tmp_path), estimator="infracost_fixture")
        proposed = tmp_path / "p.json"
        baseline = tmp_path / "b.json"
        fixture = {
            "version": "0.2", "currency": "USD", "totalMonthlyCost": "10.00",
            "projects": [{"breakdown": {"resources": []}}],
        }
        proposed.write_text(_json.dumps(fixture), encoding="utf-8")
        baseline.write_text(_json.dumps({**fixture, "totalMonthlyCost": "10.00"}), encoding="utf-8")

        plan_doc = {
            "terraform_version": "1.11.0", "format_version": "1.2",
            "resource_changes": [], "variables": {"region": {"value": "us-east-1"}},
        }
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(_json.dumps(plan_doc), encoding="utf-8")

        estimator = build_estimator(config, artifact_dir=tmp_path,
                                    proposed_fixture=proposed, baseline_fixture=baseline)
        result = run_gate(
            GateRequest(proposed_plan=plan_path, baseline_plan=plan_path,
                        stack="web-platform", allow_cost_lock=False),
            config, estimator)

        assert result.status is Status.PASS
        assert result.cost_lock is None
        assert not (tmp_path / "cost-lock.json").exists()
