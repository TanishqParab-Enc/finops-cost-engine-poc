"""Unit tests for the Infracost JSON parser - the authoritative cost path."""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.cost.infracost.parser import (
    ParsedResource,
    build_estimate,
    detect_schema,
    parse_document,
    parse_v2,
)
from finops.errors import CostEstimationError
from finops.models import Action, Cloud, CostConfidence, EstimatorTrust, NormalizedPlan, ResourceChange

pytestmark = pytest.mark.unit


def v2_doc(total: str | None, resources: list[dict] | None = None, summary_extra: dict | None = None) -> dict:
    return {
        "currency": "USD",
        "summary": {
            "total_monthly_cost": total,
            "resources": len(resources or []),
            "costed_resources": len(resources or []),
            "free_resources": 0,
            **(summary_extra or {}),
        },
        "projects": [{"project_name": "p", "path": "p", "resources": resources or []}],
    }


def v2_resource(name: str, rtype: str, monthly: str, **flags) -> dict:
    return {
        "name": name,
        "type": rtype,
        "is_supported": flags.get("is_supported", True),
        "is_free": flags.get("is_free", False),
        "cost_components": [
            {
                "name": "Instance usage",
                "unit": "hours",
                "price": flags.get("price", "0.096"),
                "quantity": "730",
                "base_monthly_cost": monthly,
                "usage_monthly_cost": flags.get("usage_monthly_cost", "0"),
                "total_monthly_cost": monthly,
            }
        ],
        "subresources": flags.get("subresources", []),
    }


class TestSchemaDetection:
    def test_detects_v2(self):
        assert detect_schema(v2_doc("10")) == "v2"

    def test_detects_v010(self):
        doc = {"currency": "USD", "totalMonthlyCost": "10", "diffTotalMonthlyCost": "5", "projects": []}
        assert detect_schema(doc) == "v0.10"

    def test_rejects_unknown(self):
        with pytest.raises(CostEstimationError, match="Unrecognised"):
            detect_schema({"hello": "world"})

    def test_rejects_non_object(self):
        with pytest.raises(CostEstimationError):
            detect_schema([])  # type: ignore[arg-type]


class TestV2Parsing:
    def test_parses_totals_and_resources(self):
        doc = v2_doc("74.08", [v2_resource("aws_instance.web", "aws_instance", "70.08")])
        parsed = parse_v2(doc)
        assert parsed.total_monthly_cost == Decimal("74.08")
        assert parsed.currency == "USD"
        assert parsed.resources["aws_instance.web"].resource_type == "aws_instance"

    def test_includes_subresource_costs_in_parent(self):
        resource = v2_resource(
            "aws_instance.web",
            "aws_instance",
            "70.08",
            subresources=[
                {
                    "name": "root_block_device",
                    "type": "",
                    "is_supported": False,
                    "is_free": False,
                    "cost_components": [
                        {
                            "name": "Storage",
                            "unit": "GB",
                            "price": "0.08",
                            "quantity": "50",
                            "base_monthly_cost": "4",
                            "usage_monthly_cost": "0",
                            "total_monthly_cost": "4",
                        }
                    ],
                }
            ],
        )
        parsed = parse_v2(v2_doc("74.08", [resource]))
        entry = parsed.resources["aws_instance.web"]
        assert entry.monthly_cost == Decimal("74.08")
        assert any("root_block_device" in c.name for c in entry.components)

    def test_subresource_marked_unsupported_does_not_flag_parent(self):
        resource = v2_resource("aws_instance.web", "aws_instance", "70.08")
        parsed = parse_v2(v2_doc("70.08", [resource]))
        assert parsed.coverage.unsupported_resources == 0
        assert parsed.resources["aws_instance.web"].confidence() is CostConfidence.PRICED

    def test_null_price_marks_no_price(self):
        resource = v2_resource("aws_thing.x", "aws_thing", None, price=None)
        parsed = parse_v2(v2_doc("0", [resource]))
        assert parsed.resources["aws_thing.x"].confidence() is CostConfidence.NO_PRICE
        assert parsed.coverage.no_price_resources == 1

    def test_usage_based_component_detected(self):
        resource = v2_resource("aws_s3_bucket.b", "aws_s3_bucket", "5", usage_monthly_cost="5")
        parsed = parse_v2(v2_doc("5", [resource]))
        assert parsed.resources["aws_s3_bucket.b"].confidence() is CostConfidence.USAGE_BASED

    def test_cloud_derived_from_resource_type(self):
        doc = v2_doc(
            "100",
            [
                v2_resource("aws_instance.a", "aws_instance", "50"),
                v2_resource("azurerm_linux_virtual_machine.b", "azurerm_linux_virtual_machine", "30"),
                v2_resource("google_compute_instance.c", "google_compute_instance", "20"),
            ],
        )
        parsed = parse_v2(doc)
        assert parsed.resources["aws_instance.a"].cloud is Cloud.AWS
        assert parsed.resources["azurerm_linux_virtual_machine.b"].cloud is Cloud.AZURE
        assert parsed.resources["google_compute_instance.c"].cloud is Cloud.GCP


class TestBuildEstimate:
    def test_incremental_is_proposed_minus_baseline(self):
        proposed = parse_document(v2_doc("175", [v2_resource("aws_instance.a", "aws_instance", "175")]))
        baseline = parse_document(v2_doc("100", [v2_resource("aws_instance.a", "aws_instance", "100")]))
        estimate = build_estimate(proposed, baseline, "infracost")
        assert estimate.previous_monthly_cost == Decimal("100")
        assert estimate.new_monthly_cost == Decimal("175")
        assert estimate.incremental_monthly_cost == Decimal("75")
        assert estimate.trust is EstimatorTrust.AUTHORITATIVE

    def test_no_baseline_treats_previous_as_zero_and_warns(self):
        proposed = parse_document(v2_doc("175", [v2_resource("aws_instance.a", "aws_instance", "175")]))
        estimate = build_estimate(proposed, None, "infracost")
        assert estimate.previous_monthly_cost == Decimal("0")
        assert estimate.incremental_monthly_cost == Decimal("175")
        assert any("No baseline" in w for w in estimate.warnings)

    def test_null_proposed_total_raises_rather_than_defaulting_to_zero(self):
        proposed = parse_document(v2_doc(None))
        with pytest.raises(CostEstimationError, match="total monthly cost"):
            build_estimate(proposed, None, "infracost")

    def test_null_baseline_total_raises(self):
        proposed = parse_document(v2_doc("100"))
        baseline = parse_document(v2_doc(None))
        with pytest.raises(CostEstimationError, match="baseline"):
            build_estimate(proposed, baseline, "infracost")

    def test_currency_mismatch_raises(self):
        proposed = parse_document(v2_doc("100"))
        baseline = parse_document(v2_doc("50"))
        baseline.currency = "EUR"
        with pytest.raises(CostEstimationError, match="currencies"):
            build_estimate(proposed, baseline, "infracost")

    def test_resource_deletion_produces_negative_delta(self):
        proposed = parse_document(v2_doc("0", []))
        baseline = parse_document(v2_doc("70", [v2_resource("aws_instance.a", "aws_instance", "70")]))
        estimate = build_estimate(proposed, baseline, "infracost")
        assert estimate.incremental_monthly_cost == Decimal("-70")
        assert estimate.resources[0].delta_monthly_cost == Decimal("-70")

    def test_annual_derived_from_monthly(self):
        proposed = parse_document(v2_doc("110"))
        baseline = parse_document(v2_doc("100"))
        estimate = build_estimate(proposed, baseline, "infracost")
        assert estimate.incremental_annual_cost == Decimal("120")

    def test_percentage_none_without_baseline(self):
        estimate = build_estimate(parse_document(v2_doc("100")), None, "infracost")
        assert estimate.incremental_percentage is None

    def test_coverage_warnings_surface(self):
        doc = v2_doc(
            "10",
            [v2_resource("aws_thing.x", "aws_thing", "10")],
            summary_extra={"resources": 3, "costed_resources": 1, "free_resources": 0},
        )
        estimate = build_estimate(parse_document(doc), None, "infracost")
        assert estimate.coverage.unsupported_resources == 2
        assert any("not supported" in w for w in estimate.warnings)

    def test_malformed_price_string_is_treated_as_no_price_not_zero(self):
        """A garbage/unparseable price must fail safe the same way a null
        price does - it must never silently become a priced $0 resource."""
        resource = v2_resource("aws_thing.x", "aws_thing", None, price="not-a-number")
        parsed = parse_v2(v2_doc("0", [resource]))
        entry = parsed.resources["aws_thing.x"]
        assert entry.confidence() is CostConfidence.NO_PRICE
        assert entry.monthly_cost is None

    def test_plan_action_is_attached_to_destroyed_and_created_resources(self):
        """The Terraform action (destroy/create/...) from the plan, not a
        guess from the delta's sign, is what the report labels resources with."""
        proposed = parse_document(
            v2_doc("50", [v2_resource("aws_instance.new", "aws_instance", "50")])
        )
        baseline = parse_document(
            v2_doc("70", [v2_resource("aws_instance.old", "aws_instance", "70")])
        )
        plan = NormalizedPlan(
            terraform_version="1.11.0",
            format_version="1.2",
            clouds=[Cloud.AWS],
            changes=[
                ResourceChange(
                    address="aws_instance.new",
                    resource_type="aws_instance",
                    name="new",
                    cloud=Cloud.AWS,
                    action=Action.CREATE,
                ),
                ResourceChange(
                    address="aws_instance.old",
                    resource_type="aws_instance",
                    name="old",
                    cloud=Cloud.AWS,
                    action=Action.DELETE,
                ),
            ],
        )
        estimate = build_estimate(proposed, baseline, "infracost", plan=plan)
        by_address = {r.address: r for r in estimate.resources}

        created = by_address["aws_instance.new"]
        destroyed = by_address["aws_instance.old"]
        assert created.action is Action.CREATE
        assert created.delta_monthly_cost == Decimal("50")
        assert destroyed.action is Action.DELETE
        assert destroyed.delta_monthly_cost == Decimal("-70")

    def test_no_plan_leaves_action_unset(self):
        """Backward compatible: a caller with no plan (e.g. a bare fixture)
        still gets a valid estimate, just without a Terraform action label."""
        proposed = parse_document(v2_doc("0", []))
        baseline = parse_document(v2_doc("70", [v2_resource("aws_instance.a", "aws_instance", "70")]))
        estimate = build_estimate(proposed, baseline, "infracost")
        assert estimate.resources[0].action is None


class TestConfidenceClassification:
    """Regression coverage for a real CI defect: `ParsedResource.confidence()`
    checked has_missing_price before the parent's own monthly_cost, so a
    resource with a genuine parent price but one null nested/optional
    component (Azure's os_disk "Disk operations", storage account's "Blob
    index") was reported as UNSUPPORTED / UNESTIMATED - contradicting
    Infracost's own totalSupportedResources/totalUnsupportedResources for the
    same run. Classification now looks at what a resource HAS
    (monthly_cost, usage-based/missing components) rather than being able to
    be overridden by one absent nested component alone.
    """

    def test_azure_vm_with_priced_parent_and_null_nested_component_is_usage_based(self):
        """Real shape from CI: parent monthlyCost=32.768, os_disk subresource
        contributes a null-cost "Disk operations" component."""
        resource = ParsedResource(
            address="azurerm_linux_virtual_machine.app",
            resource_type="azurerm_linux_virtual_machine",
            monthly_cost=Decimal("32.768"),
            is_supported=True,
            has_missing_price=True,
        )
        assert resource.confidence() is CostConfidence.USAGE_BASED

    def test_azure_managed_disk_with_priced_parent_and_null_nested_component_is_usage_based(self):
        resource = ParsedResource(
            address="azurerm_managed_disk.data",
            resource_type="azurerm_managed_disk",
            monthly_cost=Decimal("2.40"),
            is_supported=True,
            has_missing_price=True,
        )
        assert resource.confidence() is CostConfidence.USAGE_BASED

    def test_azure_storage_account_with_priced_parent_and_null_nested_component_is_usage_based(self):
        resource = ParsedResource(
            address="azurerm_storage_account.assets",
            resource_type="azurerm_storage_account",
            monthly_cost=Decimal("0.1749"),
            is_supported=True,
            has_missing_price=True,
        )
        assert resource.confidence() is CostConfidence.USAGE_BASED

    def test_gcp_resource_with_no_missing_components_remains_priced(self):
        """GCP compute resources in the same CI run had no null components
        and must stay PRICED, not be swept into USAGE_BASED by this fix."""
        resource = ParsedResource(
            address="google_compute_disk.data",
            resource_type="google_compute_disk",
            monthly_cost=Decimal("3.20"),
            is_supported=True,
        )
        assert resource.confidence() is CostConfidence.PRICED

    def test_truly_unsupported_resource_stays_unsupported(self):
        """is_supported=False must win regardless of monthly_cost/components -
        UNSUPPORTED still means Infracost does not support the resource."""
        resource = ParsedResource(
            address="aws_mystery.x",
            resource_type="aws_mystery_resource",
            monthly_cost=None,
            is_supported=False,
        )
        assert resource.confidence() is CostConfidence.UNSUPPORTED

    def test_supported_resource_with_no_monthly_cost_is_no_price(self):
        resource = ParsedResource(
            address="aws_thing.x",
            resource_type="aws_thing",
            monthly_cost=None,
            is_supported=True,
        )
        assert resource.confidence() is CostConfidence.NO_PRICE

    def test_usage_based_flag_alone_still_classifies_as_usage_based(self):
        resource = ParsedResource(
            address="aws_s3_bucket.b",
            resource_type="aws_s3_bucket",
            monthly_cost=Decimal("5"),
            is_supported=True,
            has_usage_based=True,
        )
        assert resource.confidence() is CostConfidence.USAGE_BASED

    def test_missing_price_never_promotes_an_absent_parent_cost_to_usage_based(self):
        """The parent's monthly_cost must be PRESENT for USAGE_BASED - a
        resource with no authoritative cost at all and a missing nested
        component is NO_PRICE, never USAGE_BASED."""
        resource = ParsedResource(
            address="aws_thing.y",
            resource_type="aws_thing",
            monthly_cost=None,
            is_supported=True,
            has_missing_price=True,
        )
        assert resource.confidence() is CostConfidence.NO_PRICE

    def test_free_resource_remains_free(self):
        """FREE (zero-cost, no components) must not regress: monthly_cost is
        ZERO (present, not None), so it clears the NO_PRICE/USAGE_BASED
        checks and still lands on FREE."""
        resource = ParsedResource(
            address="aws_free_thing.x",
            resource_type="aws_free_thing",
            monthly_cost=Decimal("0"),
            is_supported=True,
            is_free=True,
        )
        assert resource.confidence() is CostConfidence.FREE
