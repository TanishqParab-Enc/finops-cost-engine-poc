"""Unit tests for the Infracost JSON parser - the authoritative cost path."""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.cost.infracost.parser import (
    build_estimate,
    detect_schema,
    parse_document,
    parse_v2,
)
from finops.errors import CostEstimationError
from finops.models import Cloud, CostConfidence, EstimatorTrust

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


class TestInitialDeploymentSemantics:
    """A stack absent from the base ref is a new deployment: baseline = $0,
    never 'same as proposed' merely because nothing existed before."""

    def test_new_stack_baseline_is_zero(self):
        proposed = parse_document(v2_doc("258.62", [v2_resource("aws_lb.main", "aws_lb", "16.43")]))
        estimate = build_estimate(proposed, None, "infracost")
        assert estimate.previous_monthly_cost == Decimal("0")

    def test_new_stack_proposed_is_the_full_infracost_cost(self):
        proposed = parse_document(v2_doc("258.62"))
        estimate = build_estimate(proposed, None, "infracost")
        assert estimate.new_monthly_cost == Decimal("258.62")

    def test_new_stack_incremental_equals_the_full_proposed_cost(self):
        proposed = parse_document(v2_doc("258.62"))
        estimate = build_estimate(proposed, None, "infracost")
        assert estimate.incremental_monthly_cost == estimate.new_monthly_cost == Decimal("258.62")

    def test_existing_stack_incremental_is_proposed_minus_baseline(self):
        proposed = parse_document(v2_doc("280.00"))
        baseline = parse_document(v2_doc("258.62"))
        estimate = build_estimate(proposed, baseline, "infracost")
        assert estimate.previous_monthly_cost == Decimal("258.62")
        assert estimate.incremental_monthly_cost == Decimal("21.38")

    def test_new_stack_above_threshold_is_blocked(self):
        from finops.models import PolicyDecision, Status

        proposed = parse_document(v2_doc("258.62"))
        estimate = build_estimate(proposed, None, "infracost")
        decision = PolicyDecision(
            status=Status.FAIL if estimate.incremental_monthly_cost > 100 else Status.PASS,
            metric="incremental_monthly_cost", unit="USD/month",
            observed_value=estimate.incremental_monthly_cost, threshold_value=Decimal("100"),
            currency="USD", comparison="<=",
        )
        assert decision.status is Status.FAIL
        assert decision.exceeded_by == Decimal("158.62")

    def test_new_stack_at_or_under_threshold_passes(self):
        from finops.models import PolicyDecision, Status

        proposed = parse_document(v2_doc("80.00"))
        estimate = build_estimate(proposed, None, "infracost")
        decision = PolicyDecision(
            status=Status.PASS if estimate.incremental_monthly_cost <= 100 else Status.FAIL,
            metric="incremental_monthly_cost", unit="USD/month",
            observed_value=estimate.incremental_monthly_cost, threshold_value=Decimal("100"),
            currency="USD", comparison="<=",
        )
        assert decision.status is Status.PASS
        assert estimate.previous_monthly_cost == Decimal("0")
        assert estimate.incremental_monthly_cost == Decimal("80.00")
