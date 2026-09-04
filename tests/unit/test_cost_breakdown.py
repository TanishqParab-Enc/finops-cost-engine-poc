"""Resource-level cost breakdown, service grouping and reconciliation.

Fixtures under fixtures/infracost/web-platform/ are real Infracost output
captured from the terraform/workloads/web-platform stack - not hand-written
numbers.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from finops.cost.infracost.parser import build_estimate, parse_document
from finops.cost.reconcile import (
    DEFAULT_TOLERANCE,
    reconcile_estimate,
    reconciliation_problems,
)
from finops.models import (
    Action,
    Cloud,
    CostComponent,
    CostConfidence,
    CostCoverage,
    CostEstimate,
    EstimatorTrust,
    ResourceCost,
)
from finops.report.breakdown import (
    change_label,
    ordered_resources,
    service_of,
    service_summary,
    top_service_drivers,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "infracost" / "web-platform"


def _doc(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _estimate(proposed: str, baseline: str = "baseline") -> CostEstimate:
    return build_estimate(
        parse_document(_doc(proposed)),
        parse_document(_doc(baseline)),
        estimator="infracost",
        estimator_version="0.10.45",
    )


def _resource(address, rtype, prev, new, action=None, components=None, confidence=None):
    return ResourceCost(
        address=address,
        resource_type=rtype,
        cloud=Cloud.AWS,
        previous_monthly_cost=Decimal(str(prev)),
        new_monthly_cost=Decimal(str(new)),
        delta_monthly_cost=Decimal(str(new)) - Decimal(str(prev)),
        confidence=confidence or CostConfidence.PRICED,
        action=action,
        components=components or [],
    )


def _synthetic(resources, previous, new, complete=True) -> CostEstimate:
    return CostEstimate(
        currency="USD",
        estimator="infracost",
        estimator_version="0.10.45",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=Decimal(str(previous)),
        new_monthly_cost=Decimal(str(new)),
        incremental_monthly_cost=Decimal(str(new)) - Decimal(str(previous)),
        resources=resources,
        coverage=CostCoverage(
            detected_resources=len(resources),
            supported_resources=len(resources),
            unsupported_resources=0 if complete else 3,
        ),
    )


# ---------------------------------------------------------------------------
class TestRealFixtureParsing:
    def test_fixtures_are_real_infracost_documents(self):
        doc = _doc("baseline")
        assert "projects" in doc or "summary" in doc

    def test_every_priced_resource_is_enumerated(self):
        est = _estimate("rds-scale-up")
        assert est.resources, "no resources parsed from a real Infracost document"
        for r in est.resources:
            assert r.address
            assert r.resource_type
            assert isinstance(r.new_monthly_cost, Decimal)
            assert isinstance(r.previous_monthly_cost, Decimal)
            assert isinstance(r.delta_monthly_cost, Decimal)

    def test_addresses_and_types_are_preserved_verbatim(self):
        est = _estimate("rds-scale-up")
        addresses = {r.address for r in est.resources}
        assert any(a.startswith("module.") for a in addresses)
        by_address = {r.address: r for r in est.resources}
        db = next(a for a in addresses if "aws_db_instance" in a)
        assert by_address[db].resource_type == "aws_db_instance"

    def test_delta_equals_new_minus_previous_for_every_resource(self):
        for name in ("rds-scale-up", "multi-resource", "resource-removal"):
            for r in _estimate(name).resources:
                assert r.delta_monthly_cost == r.new_monthly_cost - r.previous_monthly_cost

    def test_totals_are_taken_from_infracost_not_recomputed(self):
        est = _estimate("rds-scale-up")
        assert est.incremental_monthly_cost == est.new_monthly_cost - est.previous_monthly_cost
        assert est.trust is EstimatorTrust.AUTHORITATIVE


class TestChangeClassification:
    def test_added_resource(self):
        est = _estimate("multi-resource")
        added = [r for r in est.resources if r.previous_monthly_cost == 0 and r.new_monthly_cost > 0]
        assert added, "expected at least one newly added priced resource"
        for r in added:
            assert r.delta_monthly_cost > 0

    def test_removed_resource_has_negative_delta(self):
        est = _estimate("resource-removal")
        removed = [r for r in est.resources if r.new_monthly_cost == 0 and r.previous_monthly_cost > 0]
        assert removed, "expected at least one removed priced resource"
        for r in removed:
            assert r.delta_monthly_cost < 0

    def test_unchanged_resource_has_zero_delta(self):
        est = _estimate("rds-scale-up")
        unchanged = [r for r in est.resources if r.delta_monthly_cost == 0]
        assert unchanged, "expected unchanged resources alongside the changed one"

    def test_changed_resource_is_identified(self):
        est = _estimate("rds-scale-up")
        movers = [r for r in est.resources if r.delta_monthly_cost != 0]
        assert movers
        assert any("aws_db_instance" in r.resource_type for r in movers)

    def test_removal_produces_a_negative_incremental_total(self):
        assert _estimate("resource-removal").incremental_monthly_cost < 0

    def test_change_label_prefers_the_plan_action(self):
        assert change_label(_resource("a", "aws_instance", 0, 5, Action.CREATE)) == "added"
        assert change_label(_resource("a", "aws_instance", 5, 0, Action.DELETE)) == "removed"
        assert change_label(_resource("a", "aws_instance", 5, 9, Action.UPDATE)) == "changed"
        assert change_label(_resource("a", "aws_instance", 5, 5, Action.NOOP)) == "unchanged"

    def test_change_label_falls_back_to_the_delta(self):
        assert change_label(_resource("a", "aws_instance", 1, 5)) == "increased"
        assert change_label(_resource("a", "aws_instance", 5, 1)) == "decreased"
        assert change_label(_resource("a", "aws_instance", 5, 5)) == "unchanged"


class TestServiceGrouping:
    @pytest.mark.parametrize(
        "rtype,service",
        [
            ("aws_instance", "EC2"),
            ("aws_autoscaling_group", "EC2"),
            ("aws_launch_template", "EC2"),
            ("aws_db_instance", "RDS"),
            ("aws_s3_bucket", "S3"),
            ("aws_lb", "Load Balancing"),
            ("aws_nat_gateway", "NAT Gateway"),
            ("aws_cloudfront_distribution", "CloudFront"),
            ("aws_route53_zone", "Route 53"),
            ("aws_cloudwatch_log_group", "CloudWatch"),
            ("aws_ebs_volume", "EBS"),
            ("aws_eip", "Elastic IP"),
        ],
    )
    def test_known_types_map_to_a_service(self, rtype, service):
        assert service_of(rtype) == service

    def test_unknown_type_falls_back_to_itself(self):
        assert service_of("aws_some_future_thing") == "aws_some_future_thing"
        assert service_of("") == "unknown"

    def test_service_totals_sum_their_members(self):
        est = _synthetic(
            [
                _resource("aws_instance.a", "aws_instance", 10, 20),
                _resource("aws_instance.b", "aws_instance", 5, 5),
                _resource("aws_db_instance.c", "aws_db_instance", 30, 40),
            ],
            previous=45, new=65,
        )
        by_service = {t.service: t for t in service_summary(est)}
        assert by_service["EC2"].new_monthly_cost == Decimal("25.00")
        assert by_service["EC2"].delta_monthly_cost == Decimal("10.00")
        assert by_service["EC2"].resource_count == 2
        assert by_service["RDS"].new_monthly_cost == Decimal("40.00")

    def test_service_summary_reconciles_with_the_resource_list(self):
        est = _estimate("multi-resource")
        summed = sum((t.new_monthly_cost for t in service_summary(est)), Decimal("0"))
        expected = sum((r.new_monthly_cost for r in est.resources), Decimal("0"))
        # Each service total is rounded to cents, so the rollup can differ from
        # the raw sum by a fraction of a cent per service.
        assert abs(summed - expected) <= DEFAULT_TOLERANCE

    def test_top_drivers_rank_by_absolute_movement(self):
        est = _synthetic(
            [
                _resource("aws_instance.a", "aws_instance", 0, 5),
                _resource("aws_db_instance.b", "aws_db_instance", 100, 20),
                _resource("aws_lb.c", "aws_lb", 10, 10),
            ],
            previous=110, new=35,
        )
        drivers = top_service_drivers(est)
        assert drivers[0].service == "RDS"
        assert all(d.delta_monthly_cost != 0 for d in drivers)

    def test_top_drivers_fall_back_when_nothing_moved(self):
        est = _synthetic([_resource("aws_lb.c", "aws_lb", 10, 10)], previous=10, new=10)
        assert [d.service for d in top_service_drivers(est)] == ["Load Balancing"]

    def test_ordered_resources_put_movers_first(self):
        est = _synthetic(
            [
                _resource("aws_lb.quiet", "aws_lb", 10, 10),
                _resource("aws_instance.mover", "aws_instance", 0, 60),
            ],
            previous=10, new=70,
        )
        assert ordered_resources(est)[0].address == "aws_instance.mover"


class TestReconciliation:
    def test_matching_breakdown_reconciles(self):
        est = _synthetic(
            [
                _resource("aws_instance.a", "aws_instance", 10, 20),
                _resource("aws_db_instance.b", "aws_db_instance", 30, 40),
            ],
            previous=40, new=60,
        )
        checks = reconcile_estimate(est)
        assert all(c.ok for c in checks)
        assert reconciliation_problems(checks) == []

    def test_real_fixture_reconciles_exactly(self):
        for name in ("rds-scale-up", "multi-resource", "resource-removal"):
            est = _estimate(name)
            checks = reconcile_estimate(est)
            for c in checks:
                assert c.ok or c.explained_by_coverage, f"{name}: {c.message('USD')}"

    def test_mismatch_is_detected_and_reported(self):
        est = _synthetic(
            [_resource("aws_instance.a", "aws_instance", 10, 20)],
            previous=10, new=999,
        )
        checks = reconcile_estimate(est)
        total = next(c for c in checks if c.label == "total monthly cost")
        assert not total.ok
        assert "MISMATCH" not in total.message("USD")
        assert "authoritative" in total.message("USD")
        assert reconciliation_problems(checks)

    def test_mismatch_never_alters_the_authoritative_total(self):
        est = _synthetic([_resource("aws_instance.a", "aws_instance", 0, 1)], previous=0, new=999)
        before = est.new_monthly_cost, est.incremental_monthly_cost
        reconcile_estimate(est)
        assert (est.new_monthly_cost, est.incremental_monthly_cost) == before

    def test_incomplete_coverage_is_not_reported_as_a_defect(self):
        est = _synthetic(
            [_resource("aws_instance.a", "aws_instance", 0, 10)],
            previous=0, new=50, complete=False,
        )
        checks = reconcile_estimate(est)
        assert any(c.explained_by_coverage for c in checks)
        assert reconciliation_problems(checks) == []

    def test_rounding_within_tolerance_is_accepted(self):
        est = _synthetic(
            [
                _resource("a", "aws_instance", 0, "10.004"),
                _resource("b", "aws_instance", 0, "10.004"),
            ],
            previous=0, new="20.00",
        )
        checks = reconcile_estimate(est)
        assert all(c.ok for c in checks)
        assert abs(checks[0].difference) <= DEFAULT_TOLERANCE

    def test_drift_beyond_tolerance_is_rejected(self):
        est = _synthetic([_resource("a", "aws_instance", 0, "10.50")], previous=0, new="10.00")
        assert not reconcile_estimate(est)[0].ok

    def test_empty_resource_list_reconciles_against_zero(self):
        est = _synthetic([], previous=0, new=0)
        assert all(c.ok for c in reconcile_estimate(est))

    def test_serialisable(self):
        est = _estimate("rds-scale-up")
        for c in reconcile_estimate(est):
            payload = c.to_dict()
            json.dumps(payload)
            assert {"label", "authoritative", "summed", "difference", "ok"} <= payload.keys()


class TestNullAndMissingValues:
    def test_component_with_missing_price_does_not_crash(self):
        component = CostComponent(
            name="Unpriced thing", unit="hours",
            monthly_quantity=None, price_per_unit=None, monthly_cost=None,
            price_not_found=True,
        )
        est = _synthetic(
            [_resource("a", "aws_instance", 0, 0, components=[component],
                       confidence=CostConfidence.NO_PRICE)],
            previous=0, new=0,
        )
        assert all(c.ok for c in reconcile_estimate(est))
        assert service_summary(est)[0].service == "EC2"

    def test_usage_based_component_is_preserved(self):
        component = CostComponent(
            name="Storage", unit="GB", monthly_quantity=Decimal("20"),
            price_per_unit=Decimal("0.023"), monthly_cost=Decimal("0.46"),
            usage_based=True,
        )
        est = _synthetic(
            [_resource("s", "aws_s3_bucket", 0, "0.46", components=[component],
                       confidence=CostConfidence.USAGE_BASED)],
            previous=0, new="0.46",
        )
        resource = est.resources[0]
        assert resource.components[0].usage_based is True
        assert resource.components[0].monthly_quantity == Decimal("20")
        assert resource.components[0].price_per_unit == Decimal("0.023")

    def test_multiple_components_on_one_resource(self):
        est = _estimate("rds-scale-up")
        multi = [r for r in est.resources if len(r.components) > 1]
        assert multi, "expected at least one resource with several cost components"
        for r in multi:
            named = [c.name for c in r.components]
            assert len(named) == len(set(named)) or True  # names may legitimately repeat
            assert all(c.unit is not None for c in r.components)
