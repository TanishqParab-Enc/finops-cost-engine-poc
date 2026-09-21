"""Cloud routing for the two common workflows.

Greenfield takes the cloud from the UI and the registry must confirm it;
brownfield never asks and resolves it from the registry alone. Both then enter
the SAME FinOps control flow, so these tests assert routing and isolation -
never a second copy of the governance logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from finops.errors import ConfigurationError
from finops.stacks import (
    expected_state_key,
    get_stack,
    load_stacks,
    select_stacks,
    stack_matrix_entry,
    validate_selection,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "config" / "finops-stacks.yml"
COST_GATE = REPO_ROOT / ".github" / "workflows" / "finops-cost-gate.yml"
DESTROY = REPO_ROOT / ".github" / "workflows" / "terraform-test-destroy.yml"

# One representative deployable stack per cloud.
CLOUD_STACKS = {
    "aws": "web-platform",
    "azure": "azure-sandbox",
    "gcp": "gcp-sandbox",
}


@pytest.fixture(scope="module")
def registry() -> dict:
    return load_stacks(REGISTRY)


@pytest.fixture(scope="module")
def cost_gate() -> dict:
    return yaml.safe_load(COST_GATE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def destroy() -> dict:
    return yaml.safe_load(DESTROY.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Greenfield: workflow_dispatch + cloud from the UI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cloud,stack_name", sorted(CLOUD_STACKS.items()))
def test_greenfield_dispatch_routes_each_cloud_to_its_own_stack(cloud, stack_name, registry):
    stack = registry[stack_name]
    validate_selection(stack, cloud, "dev")
    assert stack.cloud == cloud
    assert stack_matrix_entry(stack)["cloud"] == cloud


@pytest.mark.parametrize("cloud,stack_name", sorted(CLOUD_STACKS.items()))
def test_greenfield_rejects_a_cloud_the_registry_disagrees_with(cloud, stack_name, registry):
    """The UI selection must never silently win over the registry."""
    stack = registry[stack_name]
    for other in CLOUD_STACKS:
        if other == cloud:
            continue
        with pytest.raises(ConfigurationError):
            validate_selection(stack, other, "dev")


def test_greenfield_rejects_an_unsupported_cloud(registry):
    with pytest.raises(ConfigurationError):
        validate_selection(registry["web-platform"], "oracle", "dev")


def test_greenfield_rejects_a_missing_stack():
    with pytest.raises(ConfigurationError):
        get_stack("no-such-stack", REGISTRY)


def test_greenfield_rejects_a_mismatched_environment(registry):
    with pytest.raises(ConfigurationError):
        validate_selection(registry["azure-sandbox"], "azure", "production")


# ---------------------------------------------------------------------------
# Brownfield: pull_request, cloud resolved from the registry only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changed_file,expected_stack,expected_cloud",
    [
        ("terraform/workloads/web-platform/main.tf", "web-platform", "aws"),
        ("terraform/workloads/ecommerce-platform/main.tf", "ecommerce-platform", "aws"),
        ("terraform/workloads/azure/sandbox/main.tf", "azure-sandbox", "azure"),
        ("terraform/workloads/gcp/sandbox/main.tf", "gcp-sandbox", "gcp"),
    ],
)
def test_brownfield_resolves_cloud_from_the_registry(changed_file, expected_stack, expected_cloud):
    selected = select_stacks([changed_file], REGISTRY)
    assert [s.name for s in selected] == [expected_stack]
    assert selected[0].cloud == expected_cloud


def test_brownfield_never_needs_a_manual_cloud_selection():
    """A PR touching all three clouds resolves all three, unprompted."""
    selected = select_stacks(
        [
            "terraform/workloads/web-platform/main.tf",
            "terraform/workloads/azure/sandbox/main.tf",
            "terraform/workloads/gcp/sandbox/main.tf",
        ],
        REGISTRY,
    )
    assert {s.cloud for s in selected} == {"aws", "azure", "gcp"}


def test_brownfield_maps_an_unregistered_path_to_nothing():
    assert select_stacks(["docs/ARCHITECTURE.md"], REGISTRY) == []


# ---------------------------------------------------------------------------
# State-key routing
# ---------------------------------------------------------------------------


def test_non_aws_state_keys_follow_the_cloud_segmented_layout(registry):
    assert registry["azure-sandbox"].state_key == expected_state_key("azure", "dev", "sandbox")
    assert registry["gcp-sandbox"].state_key == expected_state_key("gcp", "dev", "sandbox")


def test_every_state_key_is_unique(registry):
    keys = [s.state_key for s in registry.values()]
    assert len(keys) == len(set(keys))


def test_no_stack_can_reach_another_clouds_state_prefix(registry):
    for stack in registry.values():
        for other in ("aws", "azure", "gcp"):
            if other == stack.cloud or stack.cloud == "aws":
                continue
            assert f"/{other}/" not in stack.state_key


# ---------------------------------------------------------------------------
# Cloud auth adapters and the common FinOps path
# ---------------------------------------------------------------------------


def test_cost_gate_wires_one_adapter_per_cloud(cost_gate):
    steps = cost_gate["jobs"]["cost-gate"]["steps"]
    conditions = {
        str(s.get("uses", "")): str(s.get("if", ""))
        for s in steps
        if "cloud-auth" in str(s.get("uses", ""))
    }
    assert any(
        "azure" in uses and cond == "matrix.stack.cloud == 'azure'"
        for uses, cond in conditions.items()
    )
    assert any(
        "gcp" in uses and cond == "matrix.stack.cloud == 'gcp'"
        for uses, cond in conditions.items()
    )


def test_destroy_offers_the_same_three_clouds(destroy):
    cloud = destroy["on"]["workflow_dispatch"]["inputs"]["cloud"]
    assert cloud["type"] == "choice"
    assert {opt.lower() for opt in cloud["options"]} == {"aws", "azure", "gcp"}


@pytest.mark.parametrize("stack_name", sorted(CLOUD_STACKS.values()))
def test_destroy_can_target_every_registered_cloud(stack_name, destroy):
    options = destroy["on"]["workflow_dispatch"]["inputs"]["stack"]["options"]
    assert stack_name in options


def test_destroy_routes_post_destroy_verification_per_cloud(destroy):
    steps = destroy["jobs"]["post-destroy-verify"]["steps"]
    verifiers = {
        str(s.get("uses", "")): str(s.get("if", ""))
        for s in steps
        if "post-destroy-verify" in str(s.get("uses", ""))
    }
    assert any(
        "azure" in uses and cond == "needs.validate-destroy.outputs.cloud == 'azure'"
        for uses, cond in verifiers.items()
    )
    assert any(
        "gcp" in uses and cond == "needs.validate-destroy.outputs.cloud == 'gcp'"
        for uses, cond in verifiers.items()
    )


def test_gcp_post_destroy_inputs_match_the_action_contract(destroy):
    """Wiring must use the action's real inputs, not invented ones."""
    action = yaml.safe_load(
        (REPO_ROOT / ".github" / "actions" / "post-destroy-verify" / "gcp" / "action.yml")
        .read_text(encoding="utf-8")
    )
    steps = destroy["jobs"]["post-destroy-verify"]["steps"]
    step = next(s for s in steps if str(s.get("uses", "")).endswith("post-destroy-verify/gcp"))
    assert set(step["with"]) == set(action["inputs"])


def test_azure_post_destroy_inputs_match_the_action_contract(destroy):
    action = yaml.safe_load(
        (REPO_ROOT / ".github" / "actions" / "post-destroy-verify" / "azure" / "action.yml")
        .read_text(encoding="utf-8")
    )
    steps = destroy["jobs"]["post-destroy-verify"]["steps"]
    step = next(s for s in steps if str(s.get("uses", "")).endswith("post-destroy-verify/azure"))
    assert set(step["with"]) == set(action["inputs"])


def test_the_finops_policy_path_is_shared_not_duplicated(cost_gate):
    """One gate, one authorization step - the governance logic must not be
    branched per cloud."""
    steps = cost_gate["jobs"]["cost-gate"]["steps"]
    gates = [s for s in steps if "finops analyze" in str(s.get("run", ""))]
    assert len(gates) == 1
    assert "cloud" not in str(gates[0].get("if", ""))

    appliers = [
        name
        for name, job in cost_gate["jobs"].items()
        for step in job.get("steps") or []
        if "terraform apply" in str(step.get("run", ""))
    ]
    assert set(appliers) == {"deploy"}


def test_every_cloud_uses_the_same_s3_backend(cost_gate, registry):
    """No stack may introduce an Azure Storage or GCS backend."""
    for stack in registry.values():
        versions = REPO_ROOT / stack.terraform_dir / "versions.tf"
        if not versions.exists():
            continue
        text = versions.read_text(encoding="utf-8")
        assert 'backend "azurerm"' not in text
        assert 'backend "gcs"' not in text


def test_no_cloud_specific_workflows_remain():
    """One cost gate and one destroy workflow serve all three clouds. A
    per-cloud copy would drift from the common governance path."""
    workflows = {p.name for p in (REPO_ROOT / ".github" / "workflows").glob("*.yml")}
    for forbidden in (
        "finops-cost-gate-azure.yml",
        "finops-cost-gate-gcp.yml",
        "terraform-destroy-azure.yml",
        "terraform-destroy-gcp.yml",
    ):
        assert forbidden not in workflows
    assert "finops-cost-gate.yml" in workflows
    assert "terraform-test-destroy.yml" in workflows
