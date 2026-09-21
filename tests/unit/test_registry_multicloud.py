"""Multi-cloud registry validation.

Additive only: every test here either exercises NEW azure/gcp behaviour or
asserts that the EXISTING AWS entries are unaffected by it. Nothing in this
file weakens or replaces an existing AWS assertion.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from finops.errors import ConfigurationError
from finops.stacks import (
    SUPPORTED_CLOUDS,
    Stack,
    expected_state_key,
    get_stack,
    load_stacks,
    validate_selection,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_REGISTRY = REPO_ROOT / "config" / "finops-stacks.yml"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "finops-stacks.yml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The real, committed registry
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRealRegistryStillLoads:
    def test_existing_aws_entries_remain_valid(self):
        stacks = load_stacks(REAL_REGISTRY)
        for name in ("aws", "web-platform", "ecommerce-platform"):
            assert name in stacks, f"{name} disappeared from the registry"
            assert stacks[name].cloud == "aws"

    def test_existing_aws_state_keys_are_untouched(self):
        """The multi-cloud key convention must NOT have been retro-applied."""
        stacks = load_stacks(REAL_REGISTRY)
        assert stacks["web-platform"].state_key == "finops-poc/dev/web-platform/terraform.tfstate"
        assert (
            stacks["ecommerce-platform"].state_key
            == "finops-poc/dev/ecommerce-platform/terraform.tfstate"
        )
        assert stacks["aws"].state_key == "finops-poc/dev/aws/terraform.tfstate"

    def test_azure_and_gcp_sandboxes_are_registered(self):
        stacks = load_stacks(REAL_REGISTRY)
        assert stacks["azure-sandbox"].cloud == "azure"
        assert stacks["gcp-sandbox"].cloud == "gcp"

    def test_multicloud_entries_carry_their_cloud_identifiers(self):
        stacks = load_stacks(REAL_REGISTRY)
        assert stacks["azure-sandbox"].subscription_id
        assert stacks["azure-sandbox"].location
        assert stacks["gcp-sandbox"].project_id
        assert stacks["gcp-sandbox"].region

    def test_no_registry_entry_leaks_a_credential(self):
        """Identifiers are fine; secrets are not."""
        raw = REAL_REGISTRY.read_text(encoding="utf-8").lower()
        for forbidden in ("client_secret", "private_key", "access_key", "secret_key", "password"):
            assert forbidden not in raw, f"registry appears to contain {forbidden}"


# ---------------------------------------------------------------------------
# Cloud-conditional required fields
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCloudConditionalFields:
    def test_azure_requires_subscription_and_location(self, tmp_path):
        registry = _write(
            tmp_path,
            """
            schema_version: "1.0"
            stacks:
              az:
                terraform_dir: terraform/workloads/azure/sandbox
                cloud: azure
                environment: dev
                state_key: finops-poc/dev/azure/sandbox/terraform.tfstate
            """,
        )
        with pytest.raises(ConfigurationError, match="subscription_id"):
            load_stacks(registry)

    def test_gcp_requires_project_and_region(self, tmp_path):
        registry = _write(
            tmp_path,
            """
            schema_version: "1.0"
            stacks:
              gc:
                terraform_dir: terraform/workloads/gcp/sandbox
                cloud: gcp
                environment: dev
                state_key: finops-poc/dev/gcp/sandbox/terraform.tfstate
            """,
        )
        with pytest.raises(ConfigurationError, match="project_id"):
            load_stacks(registry)

    def test_aws_requires_no_new_fields(self, tmp_path):
        """Backward compatibility: the AWS shape is unchanged."""
        registry = _write(
            tmp_path,
            """
            schema_version: "1.0"
            stacks:
              legacy:
                terraform_dir: terraform/workloads/legacy
                cloud: aws
                environment: dev
                state_key: finops-poc/dev/legacy/terraform.tfstate
            """,
        )
        stack = load_stacks(registry)["legacy"]
        assert stack.subscription_id is None
        assert stack.project_id is None

    def test_unsupported_cloud_is_rejected(self, tmp_path):
        registry = _write(
            tmp_path,
            """
            schema_version: "1.0"
            stacks:
              oracle:
                terraform_dir: terraform/workloads/oracle
                cloud: oci
                environment: dev
                state_key: finops-poc/dev/oci/x/terraform.tfstate
            """,
        )
        with pytest.raises(ConfigurationError, match="unsupported cloud"):
            load_stacks(registry)

    def test_supported_clouds_are_exactly_three(self):
        assert SUPPORTED_CLOUDS == ("aws", "azure", "gcp")
