"""State-key isolation and fail-closed cloud/environment selection.

These are the security-relevant registry tests: they prove an Azure or GCP run
cannot be pointed at an AWS workload's Terraform state, and that an operator's
cloud/environment selection is checked against the trusted registry BEFORE any
credential exchange or Terraform command.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from finops.errors import ConfigurationError
from finops.stacks import (
    Stack,
    expected_state_key,
    load_stacks,
    select_stacks,
    validate_selection,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_REGISTRY = REPO_ROOT / "config" / "finops-stacks.yml"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "finops-stacks.yml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _stack(**overrides) -> Stack:
    base = dict(
        name="azure-sandbox",
        terraform_dir="terraform/workloads/azure/sandbox",
        cloud="azure",
        deployable=True,
        environment="dev",
        state_key="finops-poc/dev/azure/sandbox/terraform.tfstate",
        paths=("terraform/workloads/azure/sandbox/",),
    )
    base.update(overrides)
    return Stack(**base)


# ---------------------------------------------------------------------------
# State key isolation
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestStateKeyIsolation:
    def test_expected_state_key_is_deterministic(self):
        assert (
            expected_state_key("azure", "dev", "sandbox")
            == "finops-poc/dev/azure/sandbox/terraform.tfstate"
        )
        assert (
            expected_state_key("gcp", "prod", "ecommerce-platform")
            == "finops-poc/prod/gcp/ecommerce-platform/terraform.tfstate"
        )

    def test_every_registered_stack_has_a_unique_state_key(self):
        stacks = load_stacks(REAL_REGISTRY)
        keys = [s.state_key for s in stacks.values()]
        assert len(keys) == len(set(keys))

    def test_clouds_do_not_share_a_state_prefix(self):
        stacks = load_stacks(REAL_REGISTRY)
        assert stacks["azure-sandbox"].state_key != stacks["gcp-sandbox"].state_key
        assert "/azure/" in stacks["azure-sandbox"].state_key
        assert "/gcp/" in stacks["gcp-sandbox"].state_key

    def test_azure_cannot_claim_an_aws_workload_state_key(self, tmp_path):
        """The exact accident this guard exists to prevent."""
        registry = _write(
            tmp_path,
            """
            schema_version: "1.0"
            stacks:
              rogue:
                terraform_dir: terraform/workloads/azure/sandbox
                cloud: azure
                environment: dev
                subscription_id: 00000000-0000-0000-0000-000000000000
                location: eastus
                state_key: finops-poc/dev/web-platform/terraform.tfstate
            """,
        )
        with pytest.raises(ConfigurationError, match="non-conforming state_key"):
            load_stacks(registry)

    def test_gcp_cannot_claim_an_azure_state_key(self, tmp_path):
        registry = _write(
            tmp_path,
            """
            schema_version: "1.0"
            stacks:
              rogue:
                terraform_dir: terraform/workloads/gcp/sandbox
                cloud: gcp
                environment: dev
                project_id: example-project
                region: us-central1
                state_key: finops-poc/dev/azure/sandbox/terraform.tfstate
            """,
        )
        with pytest.raises(ConfigurationError, match="state_key targets"):
            load_stacks(registry)

    def test_environment_cannot_be_crossed_in_the_state_key(self, tmp_path):
        """A dev-registered stack must not write prod state."""
        registry = _write(
            tmp_path,
            """
            schema_version: "1.0"
            stacks:
              rogue:
                terraform_dir: terraform/workloads/azure/sandbox
                cloud: azure
                environment: dev
                subscription_id: 00000000-0000-0000-0000-000000000000
                location: eastus
                state_key: finops-poc/prod/azure/sandbox/terraform.tfstate
            """,
        )
        with pytest.raises(ConfigurationError, match="state_key targets"):
            load_stacks(registry)

    def test_aws_legacy_keys_are_exempt_from_the_new_convention(self, tmp_path):
        """Backward compatibility guard - this is why AWS is excluded."""
        registry = _write(
            tmp_path,
            """
            schema_version: "1.0"
            stacks:
              web-platform:
                terraform_dir: terraform/workloads/web-platform
                cloud: aws
                environment: dev
                state_key: finops-poc/dev/web-platform/terraform.tfstate
            """,
        )
        assert load_stacks(registry)["web-platform"].state_key.endswith("terraform.tfstate")


# ---------------------------------------------------------------------------
# Fail-closed selection
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCloudSelectionValidation:
    def test_matching_selection_passes(self):
        stack = _stack()
        assert validate_selection(stack, "azure", "dev") is stack

    def test_cloud_mismatch_fails_closed(self):
        """cloud=aws + an Azure stack must never reach Terraform."""
        with pytest.raises(ConfigurationError, match="Cloud mismatch"):
            validate_selection(_stack(), "aws", "dev")

    def test_gcp_selection_against_azure_stack_fails_closed(self):
        with pytest.raises(ConfigurationError, match="Cloud mismatch"):
            validate_selection(_stack(), "gcp", "dev")

    def test_environment_mismatch_fails_closed(self):
        with pytest.raises(ConfigurationError, match="Environment mismatch"):
            validate_selection(_stack(), "azure", "prod")

    def test_non_deployable_stack_fails_closed_when_deployability_required(self):
        with pytest.raises(ConfigurationError, match="not deployable"):
            validate_selection(_stack(deployable=False), "azure", "dev", require_deployable=True)

    def test_non_deployable_stack_may_still_be_priced(self):
        """Pricing/reporting a non-deployable stack stays allowed."""
        stack = _stack(deployable=False)
        assert validate_selection(stack, "azure", "dev", require_deployable=False) is stack

    def test_real_registry_entries_validate_against_their_own_metadata(self):
        stacks = load_stacks(REAL_REGISTRY)
        for stack in stacks.values():
            assert validate_selection(stack, stack.cloud, stack.environment) is stack


# ---------------------------------------------------------------------------
# Each cloud's gate must only claim its own stacks. Adding Azure/GCP entries to
# the shared registry previously made the AWS gate try to price an Azure stack
# with AWS-only credentials.
# ---------------------------------------------------------------------------


def test_aws_gate_does_not_claim_azure_stack():
    selected = select_stacks(
        ["terraform/workloads/azure/sandbox/main.tf"], REAL_REGISTRY, cloud="aws"
    )
    assert selected == []


def test_azure_gate_does_not_claim_aws_stack():
    selected = select_stacks(
        ["terraform/workloads/ecommerce-platform/main.tf"], REAL_REGISTRY, cloud="azure"
    )
    assert selected == []


def test_azure_gate_claims_its_own_stack():
    names = [s.name for s in select_stacks(
        ["terraform/workloads/azure/sandbox/main.tf"], REAL_REGISTRY, cloud="azure"
    )]
    assert names == ["azure-sandbox"]


def test_unfiltered_selection_is_unchanged():
    """Omitting cloud must keep the pre-multicloud behaviour."""
    names = [s.name for s in select_stacks(
        ["terraform/workloads/azure/sandbox/main.tf"], REAL_REGISTRY
    )]
    assert names == ["azure-sandbox"]


def test_select_stacks_rejects_unsupported_cloud():
    with pytest.raises(ConfigurationError):
        select_stacks(["terraform/aws/main.tf"], REAL_REGISTRY, cloud="oracle")
