"""Unit tests for Terraform plan normalisation."""

from __future__ import annotations

import json

import pytest

from finops.errors import PlanError
from finops.models import Action, Cloud
from finops.plan.normalizer import (
    detect_cloud,
    normalize_action,
    normalize_plan,
    normalize_plan_file,
)

pytestmark = pytest.mark.unit


def _plan(resource_changes: list[dict], **extra) -> dict:
    return {
        "format_version": "1.2",
        "terraform_version": "1.11.0",
        "planned_values": {"root_module": {"resources": []}},
        "resource_changes": resource_changes,
        **extra,
    }


def _change(rtype: str, actions: list[str], after=None, before=None, provider="") -> dict:
    return {
        "address": f"{rtype}.example",
        "mode": "managed",
        "type": rtype,
        "name": "example",
        "provider_name": provider or f"registry.terraform.io/hashicorp/{rtype.split('_')[0]}",
        "change": {"actions": actions, "before": before, "after": after or {}},
    }


class TestDetectCloud:
    @pytest.mark.parametrize(
        "resource_type,expected",
        [
            ("aws_instance", Cloud.AWS),
            ("aws_ebs_volume", Cloud.AWS),
            ("azurerm_linux_virtual_machine", Cloud.AZURE),
            ("azuread_group", Cloud.AZURE),
            ("google_compute_instance", Cloud.GCP),
            ("kubernetes_deployment", Cloud.UNKNOWN),
        ],
    )
    def test_from_resource_type(self, resource_type, expected):
        assert detect_cloud(resource_type) is expected

    def test_falls_back_to_provider_name(self):
        assert detect_cloud("weird_thing", "registry.terraform.io/hashicorp/google") is Cloud.GCP


class TestNormalizeAction:
    @pytest.mark.parametrize(
        "actions,expected",
        [
            (["create"], Action.CREATE),
            (["delete"], Action.DELETE),
            (["update"], Action.UPDATE),
            (["no-op"], Action.NOOP),
            (["read"], Action.READ),
            (["delete", "create"], Action.REPLACE),
            (["create", "delete"], Action.REPLACE),
            ([], Action.NOOP),
        ],
    )
    def test_actions(self, actions, expected):
        assert normalize_action(actions) is expected


class TestNormalizePlan:
    def test_rejects_missing_format_version(self):
        with pytest.raises(PlanError, match="format_version"):
            normalize_plan({"terraform_version": "1.11.0"})

    def test_rejects_unsupported_format_version(self):
        with pytest.raises(PlanError, match="Unsupported"):
            normalize_plan({"format_version": "9.0", "resource_changes": []})

    def test_rejects_errored_plan(self):
        with pytest.raises(PlanError, match="errored"):
            normalize_plan(_plan([], errored=True))

    def test_skips_data_sources(self):
        plan = _plan([{**_change("aws_ami", ["read"]), "mode": "data"}])
        assert normalize_plan(plan).changes == []

    def test_collects_clouds_from_cost_relevant_changes_only(self):
        plan = _plan(
            [
                _change("aws_instance", ["create"], {"instance_type": "t3.micro"}),
                _change("google_compute_instance", ["no-op"]),
            ]
        )
        result = normalize_plan(plan)
        assert result.clouds == [Cloud.AWS]
        assert len(result.cost_relevant_changes) == 1

    def test_extracts_region_from_provider_config(self):
        plan = _plan(
            [_change("aws_instance", ["create"], {"instance_type": "t3.micro"})],
            configuration={
                "provider_config": {
                    "aws": {
                        "name": "aws",
                        "expressions": {"region": {"constant_value": "eu-west-1"}},
                    }
                }
            },
        )
        assert normalize_plan(plan).changes[0].region == "eu-west-1"

    def test_resource_attribute_beats_provider_region(self):
        plan = _plan(
            [_change("azurerm_managed_disk", ["create"], {"location": "westeurope"})],
            configuration={
                "provider_config": {
                    "azurerm": {"name": "azurerm", "expressions": {"region": {"constant_value": "eastus"}}}
                }
            },
        )
        assert normalize_plan(plan).changes[0].region == "westeurope"

    def test_derives_aws_region_from_availability_zone(self):
        plan = _plan([_change("aws_ebs_volume", ["create"], {"availability_zone": "ap-south-1b"})])
        assert normalize_plan(plan).changes[0].region == "ap-south-1"

    def test_derives_gcp_region_from_zone(self):
        plan = _plan([_change("google_compute_disk", ["create"], {"zone": "us-central1-a"})])
        assert normalize_plan(plan).changes[0].region == "us-central1"


class TestFingerprint:
    def test_is_stable_across_calls(self):
        plan = _plan([_change("aws_instance", ["create"], {"instance_type": "t3.micro"})])
        assert normalize_plan(plan).fingerprint() == normalize_plan(plan).fingerprint()

    def test_is_order_independent(self):
        a = _change("aws_instance", ["create"], {"instance_type": "t3.micro"})
        b = _change("aws_ebs_volume", ["create"], {"size": 100})
        first = normalize_plan(_plan([a, b])).fingerprint()
        second = normalize_plan(_plan([b, a])).fingerprint()
        assert first == second

    def test_changes_when_attributes_change(self):
        small = normalize_plan(
            _plan([_change("aws_instance", ["create"], {"instance_type": "t3.micro"})])
        ).fingerprint()
        large = normalize_plan(
            _plan([_change("aws_instance", ["create"], {"instance_type": "m5.4xlarge"})])
        ).fingerprint()
        assert small != large

    def test_ignores_non_cost_relevant_changes(self):
        base = [_change("aws_instance", ["create"], {"instance_type": "t3.micro"})]
        with_noop = base + [_change("aws_vpc", ["no-op"])]
        assert (
            normalize_plan(_plan(base)).fingerprint()
            == normalize_plan(_plan(with_noop)).fingerprint()
        )


class TestRealPlanFiles:
    @pytest.mark.parametrize("cloud,expected", [("aws", Cloud.AWS), ("azure", Cloud.AZURE), ("gcp", Cloud.GCP)])
    def test_generated_plans_normalize(self, plans_dir, cloud, expected):
        plan = normalize_plan_file(plans_dir / f"{cloud}-pass.json")
        assert plan.clouds == [expected]
        assert plan.cost_relevant_changes
        assert plan.fingerprint().startswith("sha256:")

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(PlanError, match="not found"):
            normalize_plan_file(tmp_path / "nope.json")

    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(PlanError, match="valid JSON"):
            normalize_plan_file(bad)

    def test_fail_scenario_has_more_resources_than_pass(self, plans_dir):
        pass_plan = normalize_plan_file(plans_dir / "aws-pass.json")
        fail_plan = normalize_plan_file(plans_dir / "aws-fail.json")
        assert len(fail_plan.cost_relevant_changes) > len(pass_plan.cost_relevant_changes)
        assert pass_plan.fingerprint() != fail_plan.fingerprint()
