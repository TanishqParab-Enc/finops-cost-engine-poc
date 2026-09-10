"""Fail-closed regression tests for the deployed-baseline requirement.

The Cost Gate prices a change against the stack's ACTUALLY deployed state.
Two situations look superficially similar and must never be conflated:

A) The stack's remote backend is reachable and simply holds no state yet -
   a positively-established greenfield stack. Baseline is a real, empty
   document and prices at $0, so incremental == full proposed cost.

B) The expected remote backend/state could not be reached or validated at
   all. The deployed cost is UNKNOWN. Treating that as $0 would understate
   every incremental cost and could mint a deployment-authorising cost lock
   for a delta nobody reviewed - so it must fail closed as
   COST_ESTIMATION / BASELINE_UNAVAILABLE.

These are stack-agnostic: nothing here names a real registered stack.
"""

from __future__ import annotations

import json

import pytest
import yaml

from finops.cost.fixture_estimator import InfracostFixtureEstimator
from finops.errors import BaselineUnavailableError, FailureCategory
from finops.gate import GateRequest, run_gate
from finops.models import Status
from finops.plan.state_shim import state_json_to_plan_json

from ..conftest import INFRACOST_FIXTURES, PLANS_DIR, make_config
from .test_workflow_dispatch_governance import REPO_ROOT, WORKFLOW_PATH

pytestmark = pytest.mark.unit


def fixture_estimator(scenario: str = "pass") -> InfracostFixtureEstimator:
    return InfracostFixtureEstimator(
        proposed_fixture=INFRACOST_FIXTURES / f"aws-{scenario}.json",
        baseline_fixture=INFRACOST_FIXTURES / "aws-baseline.json",
    )


def gate_error_codes(result) -> set[str]:
    return {e.get("code") for e in result.errors}


class TestBaselineUnavailableFailsClosed:
    """Case B: the backend could not be read at all."""

    def test_missing_baseline_is_a_hard_error_when_required(self, tmp_path):
        config = make_config(output_dir=str(tmp_path / ".finops"), threshold=100)
        result = run_gate(
            GateRequest(
                proposed_plan=PLANS_DIR / "aws-pass.json",
                baseline_plan=None,
                require_baseline=True,
            ),
            config,
            fixture_estimator(),
        )
        assert result.status is Status.ERROR
        assert "BASELINE_UNAVAILABLE" in gate_error_codes(result)

    def test_error_is_categorised_as_cost_estimation(self, tmp_path):
        config = make_config(output_dir=str(tmp_path / ".finops"), threshold=100)
        result = run_gate(
            GateRequest(
                proposed_plan=PLANS_DIR / "aws-pass.json",
                require_baseline=True,
            ),
            config,
            fixture_estimator(),
        )
        entry = next(e for e in result.errors if e.get("code") == "BASELINE_UNAVAILABLE")
        assert entry["category"] == FailureCategory.COST_ESTIMATION.value

    def test_unreadable_baseline_path_is_a_hard_error(self, tmp_path):
        config = make_config(output_dir=str(tmp_path / ".finops"), threshold=100)
        result = run_gate(
            GateRequest(
                proposed_plan=PLANS_DIR / "aws-pass.json",
                baseline_plan=tmp_path / "never-written.json",
                require_baseline=True,
            ),
            config,
            fixture_estimator(),
        )
        assert result.status is Status.ERROR
        assert "BASELINE_UNAVAILABLE" in gate_error_codes(result)

    def test_no_cost_lock_is_minted_when_the_baseline_is_unavailable(self, tmp_path):
        """A cost lock authorises deployment - an unknown baseline must never
        produce one, even for a change that would otherwise price as a PASS."""
        config = make_config(output_dir=str(tmp_path / ".finops"), threshold=100_000)
        result = run_gate(
            GateRequest(
                proposed_plan=PLANS_DIR / "aws-pass.json",
                require_baseline=True,
            ),
            config,
            fixture_estimator(),
        )
        assert result.cost_lock is None
        assert result.status is not Status.PASS
        assert result.exit_code != 0

    def test_baseline_unavailable_error_carries_its_own_code(self):
        exc = BaselineUnavailableError("x", detail="y")
        assert exc.to_dict()["code"] == "BASELINE_UNAVAILABLE"
        assert exc.to_dict()["category"] == FailureCategory.COST_ESTIMATION.value


class TestGreenfieldRemainsAZeroBaseline:
    """Case A: reachable backend, no deployed state - still $0, never an error."""

    def test_empty_state_document_reshapes_into_an_empty_baseline(self):
        plan_doc = state_json_to_plan_json({"format_version": "1.0"})
        assert plan_doc["planned_values"] == {"root_module": {}}
        assert plan_doc["resource_changes"] == []

    def test_an_empty_baseline_document_satisfies_require_baseline(self, tmp_path):
        """The greenfield path writes a real (empty) baseline document, so the
        fail-closed check must not fire for it."""
        baseline = tmp_path / "baseline-plan.json"
        baseline.write_text(
            json.dumps(state_json_to_plan_json({"format_version": "1.0"})),
            encoding="utf-8",
        )
        config = make_config(output_dir=str(tmp_path / ".finops"), threshold=100)
        result = run_gate(
            GateRequest(
                proposed_plan=PLANS_DIR / "aws-pass.json",
                baseline_plan=baseline,
                require_baseline=True,
            ),
            config,
            fixture_estimator(),
        )
        assert "BASELINE_UNAVAILABLE" not in gate_error_codes(result)
        assert result.status is not Status.ERROR


class TestPullRequestPathUnchanged:
    """require_baseline is opt-in: every existing caller keeps prior behaviour."""

    def test_require_baseline_defaults_to_false(self):
        assert GateRequest(proposed_plan=PLANS_DIR / "aws-pass.json").require_baseline is False

    def test_absent_baseline_without_the_flag_still_prices_normally(self, tmp_path):
        config = make_config(output_dir=str(tmp_path / ".finops"), threshold=100)
        result = run_gate(
            GateRequest(proposed_plan=PLANS_DIR / "aws-pass.json", baseline_plan=None),
            config,
            fixture_estimator(),
        )
        assert "BASELINE_UNAVAILABLE" not in gate_error_codes(result)
        assert result.status is not Status.ERROR


class TestWorkflowEnforcesFailClosed:
    """The workflow must actually drive the behaviour proven above."""

    @pytest.fixture(scope="class")
    @classmethod
    def workflow(cls) -> dict:
        return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    def test_baseline_step_is_not_continue_on_error(self, workflow):
        steps = workflow["jobs"]["cost-gate"]["steps"]
        baseline = next(s for s in steps if s.get("id") == "baseline")
        assert baseline.get("continue-on-error") is not True

    def test_baseline_step_still_never_uses_a_local_backend(self, workflow):
        steps = workflow["jobs"]["cost-gate"]["steps"]
        baseline = next(s for s in steps if s.get("id") == "baseline")
        assert 'backend "local"' not in baseline["run"]
        assert "BASELINE_UNAVAILABLE" in baseline["run"]

    def test_action_plan_step_stays_best_effort(self, workflow):
        """Resource-action labelling is cosmetic and must not fail the gate."""
        steps = workflow["jobs"]["cost-gate"]["steps"]
        action = next(s for s in steps if s.get("id") == "action-plan")
        assert action["continue-on-error"] is True

    def test_gate_step_requires_a_baseline_and_never_falls_through(self, workflow):
        steps = workflow["jobs"]["cost-gate"]["steps"]
        gate = next(s for s in steps if s.get("id") == "gate")
        script = gate["run"]
        assert "--require-baseline" in script
        assert "BASELINE_UNAVAILABLE" in script
        # The old fall-through ("treat full proposed cost as incremental")
        # must be gone.
        assert "proceeding as if no baseline exists" not in script


class TestDeployEnvironmentIsRegistryDriven:
    """The deploy job's Environment and state key come from the registry."""

    @pytest.fixture(scope="class")
    @classmethod
    def workflow(cls) -> dict:
        return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    @pytest.fixture(scope="class")
    @classmethod
    def registry(cls) -> dict:
        return yaml.safe_load(
            (REPO_ROOT / "config" / "finops-stacks.yml").read_text(encoding="utf-8")
        )["stacks"]

    def test_target_env_is_not_hard_coded(self, workflow):
        env = workflow["jobs"]["deploy"]["env"]
        assert env["TARGET_ENV"] == "${{ matrix.stack.environment }}"
        assert env["TARGET_ENV"] != "dev"

    def test_github_environment_is_registry_driven(self, workflow):
        """The Environment gate itself must still exist - only its name is
        now resolved from the registry rather than pinned."""
        environment = workflow["jobs"]["deploy"]["environment"]
        assert environment["name"] == "${{ matrix.stack.environment }}"

    def test_deploy_backend_key_is_the_registry_state_key(self, workflow):
        steps = workflow["jobs"]["deploy"]["steps"]
        plan = next(s for s in steps if s.get("id") == "plan")
        assert 'key=${{ matrix.stack.state_key }}' in plan["run"]
        assert 'backend "local"' not in plan["run"]

    def test_deploy_revalidates_environment_and_state_key_against_the_registry(self, workflow):
        steps = workflow["jobs"]["deploy"]["steps"]
        verify = next(
            s for s in steps if s.get("name") == "Verify the stack is deployable (trusted registry)"
        )
        assert "TARGET_ENV" in verify["run"]
        assert "DEPLOY_STATE_KEY" in verify["run"]
        assert "State key mismatch" in verify["run"]
        env = workflow["jobs"]["deploy"]["env"]
        assert env["DEPLOY_STATE_KEY"] == "${{ matrix.stack.state_key }}"

    def test_registered_environments_resolve_to_their_own_state_keys(self, registry):
        """Whatever environment a stack is registered for, its state key must
        belong to that environment - so a registry-driven TARGET_ENV can never
        point a stack at another environment's state."""
        for name, stack in registry.items():
            assert f"/{stack['environment']}/" in stack["state_key"], name

    def test_web_platform_still_resolves_to_dev_and_its_own_state_key(self, registry):
        stack = registry["web-platform"]
        assert stack["environment"] == "dev"
        assert stack["state_key"] == "finops-poc/dev/web-platform/terraform.tfstate"

    def test_saved_reviewed_plan_is_what_gets_applied(self, workflow):
        steps = workflow["jobs"]["deploy"]["steps"]
        plan = next(s for s in steps if s.get("id") == "plan")
        apply = next(s for s in steps if "terraform apply" in str(s.get("run", "")))
        assert "-out=tfplan.binary" in plan["run"]
        assert "tfplan.binary" in apply["run"]
