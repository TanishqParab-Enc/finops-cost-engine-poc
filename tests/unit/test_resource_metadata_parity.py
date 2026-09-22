"""Common metadata extraction, cloud adapters, and the Terraform/Infracost join.

These cover the parity requirement directly: the SAME engine must produce
equivalent reporting depth for AWS, Azure and GCP, and the AWS service labels
that already existed must not move.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.models import Action, Cloud, CostConfidence, CostEstimate, EstimatorTrust
from finops.models import NormalizedPlan, ResourceChange, ResourceCost
from finops.report.breakdown import service_of
from finops.report.clouds import adapter_for, extract_configuration
from finops.report.join import build_view, join_estimate_with_plan
from finops.report.metadata import (
    FieldSpec,
    configuration_delta,
    extract_with,
    gigabytes,
    resolve,
)


# ---------------------------------------------------------------------------
# Extraction primitives
# ---------------------------------------------------------------------------


def test_dotted_path_walks_nested_blocks():
    spec = FieldSpec("OS disk type", ("os_disk.0.storage_account_type",))
    values = {"os_disk": [{"storage_account_type": "StandardSSD_LRS"}]}
    assert resolve(values, spec) == "StandardSSD_LRS"


def test_first_non_empty_candidate_wins():
    spec = FieldSpec("VM size", ("size", "vm_size"))
    assert resolve({"size": "", "vm_size": "Standard_B2s"}, spec) == "Standard_B2s"


def test_missing_attribute_is_omitted_not_guessed():
    spec = FieldSpec("Instance type", ("instance_type",))
    assert resolve({}, spec) is None
    assert extract_with((spec,), {}) == {}


def test_formatter_failure_falls_back_to_raw_value():
    """A malformed plan value must never break the report."""
    spec = FieldSpec("Size", ("size",), gigabytes)
    assert resolve({"size": "not-a-number"}, spec) == "not-a-number"


def test_missing_index_does_not_raise():
    spec = FieldSpec("Boot disk", ("boot_disk.5.size",))
    assert resolve({"boot_disk": []}, spec) is None


def test_configuration_delta_reports_moves_and_removals():
    before = {"VM size": "Standard_B1s", "Zone": "1"}
    after = {"VM size": "Standard_B2s"}
    delta = configuration_delta(before, after)
    assert delta["VM size"] == ("Standard_B1s", "Standard_B2s")
    assert delta["Zone"] == ("1", None)


# ---------------------------------------------------------------------------
# AWS regression: existing service labels must not move
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resource_type,expected",
    [
        ("aws_instance", "EC2"),
        ("aws_autoscaling_group", "EC2"),
        ("aws_launch_template", "EC2"),
        ("aws_ebs_volume", "EBS"),
        ("aws_db_instance", "RDS"),
        ("aws_rds_cluster", "RDS"),
        ("aws_db_subnet_group", "RDS"),
        ("aws_elasticache_cluster", "ElastiCache"),
        ("aws_dynamodb_table", "DynamoDB"),
        ("aws_s3_bucket", "S3"),
        ("aws_lb", "Load Balancing"),
        ("aws_nat_gateway", "NAT Gateway"),
        ("aws_eip", "Elastic IP"),
        ("aws_cloudwatch_log_group", "CloudWatch"),
        ("aws_sqs_queue", "SQS"),
        ("aws_secretsmanager_secret", "Secrets Manager"),
        ("aws_efs_file_system", "EFS"),
    ],
)
def test_aws_service_labels_are_unchanged(resource_type, expected):
    assert service_of(resource_type) == expected


def test_aws_specific_prefix_still_beats_the_broader_one():
    """aws_db_instance must resolve before the aws_db_ catch-all."""
    assert service_of("aws_db_instance") == "RDS"
    assert service_of("aws_db_parameter_group") == "RDS"


# ---------------------------------------------------------------------------
# Azure / GCP service classification - the naive fallback is gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resource_type,expected",
    [
        ("azurerm_linux_virtual_machine", "Virtual Machines"),
        ("azurerm_windows_virtual_machine", "Virtual Machines"),
        ("azurerm_managed_disk", "Managed Disks"),
        ("azurerm_storage_account", "Storage"),
        ("azurerm_virtual_network", "Virtual Network"),
        ("azurerm_subnet", "Virtual Network"),
        ("azurerm_network_security_group", "Virtual Network"),
        ("azurerm_postgresql_flexible_server", "PostgreSQL"),
        ("azurerm_redis_cache", "Cache for Redis"),
        ("azurerm_public_ip", "Public IP"),
        ("azurerm_key_vault", "Key Vault"),
    ],
)
def test_azure_services_are_meaningful(resource_type, expected):
    assert service_of(resource_type) == expected


@pytest.mark.parametrize(
    "resource_type,expected",
    [
        ("google_compute_instance", "Compute Engine"),
        ("google_compute_disk", "Persistent Disk"),
        ("google_compute_network", "VPC Network"),
        ("google_compute_subnetwork", "VPC Network"),
        ("google_compute_firewall", "VPC Network"),
        ("google_storage_bucket", "Cloud Storage"),
        ("google_sql_database_instance", "Cloud SQL"),
        ("google_redis_instance", "Memorystore"),
        ("google_service_account", "IAM"),
    ],
)
def test_gcp_services_are_meaningful(resource_type, expected):
    assert service_of(resource_type) == expected


def test_the_old_first_token_fallback_is_gone():
    """Regression: these produced "Linux", "Managed" and "Compute"."""
    assert service_of("azurerm_linux_virtual_machine") != "Linux"
    assert service_of("azurerm_managed_disk") != "Managed"
    assert service_of("google_compute_disk") != "Compute"


def test_unknown_resource_falls_back_to_its_terraform_type():
    assert service_of("azurerm_brand_new_thing") == "azurerm_brand_new_thing"
    assert service_of("totally_unknown") == "totally_unknown"


# ---------------------------------------------------------------------------
# Equivalent reporting depth across clouds
# ---------------------------------------------------------------------------

AWS_VM = {
    "instance_type": "t3.large",
    "region": "us-east-1",
    "root_block_device": [{"volume_size": 50, "volume_type": "gp3"}],
}
AZURE_VM = {
    "size": "Standard_B2s",
    "location": "eastus",
    "os_disk": [{"storage_account_type": "StandardSSD_LRS", "disk_size_gb": 30}],
}
GCP_VM = {
    "machine_type": "e2-small",
    "zone": "us-central1-a",
    "boot_disk": [{"initialize_params": [{"size": 20, "type": "pd-balanced"}]}],
}


def test_compute_sizing_is_exposed_for_every_cloud():
    aws = extract_configuration("aws_instance", AWS_VM)
    azure = extract_configuration("azurerm_linux_virtual_machine", AZURE_VM)
    gcp = extract_configuration("google_compute_instance", GCP_VM)

    assert aws["Instance type"] == "t3.large"
    assert azure["VM size"] == "Standard_B2s"
    assert gcp["Machine type"] == "e2-small"


def test_location_is_exposed_for_every_cloud():
    assert extract_configuration("aws_instance", AWS_VM)["Region"] == "us-east-1"
    assert extract_configuration("azurerm_linux_virtual_machine", AZURE_VM)["Location"] == "eastus"
    assert extract_configuration("google_compute_instance", GCP_VM)["Location"] == "us-central1-a"


def test_boot_disk_size_and_type_are_exposed_for_every_cloud():
    aws = extract_configuration("aws_instance", AWS_VM)
    azure = extract_configuration("azurerm_linux_virtual_machine", AZURE_VM)
    gcp = extract_configuration("google_compute_instance", GCP_VM)

    assert aws["Root disk"] == "50 GB" and aws["Root disk type"] == "gp3"
    assert azure["OS disk size"] == "30 GB" and azure["OS disk type"] == "StandardSSD_LRS"
    assert gcp["Boot disk"] == "20 GB" and gcp["Boot disk type"] == "pd-balanced"


def test_every_cloud_reports_a_comparable_number_of_compute_facts():
    """Parity is about depth, not identical field names."""
    depths = [
        len(extract_configuration("aws_instance", AWS_VM)),
        len(extract_configuration("azurerm_linux_virtual_machine", AZURE_VM)),
        len(extract_configuration("google_compute_instance", GCP_VM)),
    ]
    assert min(depths) >= 4, depths


def test_storage_detail_is_exposed_for_every_cloud():
    aws = extract_configuration("aws_s3_bucket", {"bucket": "b", "region": "us-east-1"})
    azure = extract_configuration(
        "azurerm_storage_account",
        {"account_tier": "Standard", "account_replication_type": "LRS", "location": "eastus"},
    )
    gcp = extract_configuration(
        "google_storage_bucket", {"storage_class": "STANDARD", "location": "US"}
    )
    assert aws and azure["Replication"] == "LRS" and gcp["Storage class"] == "STANDARD"


def test_database_detail_is_exposed_for_every_cloud():
    aws = extract_configuration(
        "aws_db_instance",
        {"engine": "postgres", "instance_class": "db.t3.medium", "allocated_storage": 100},
    )
    azure = extract_configuration(
        "azurerm_postgresql_flexible_server", {"sku_name": "GP_Standard_D2s_v3", "storage_mb": 32768}
    )
    gcp = extract_configuration(
        "google_sql_database_instance",
        {"database_version": "POSTGRES_15", "settings": [{"tier": "db-f1-micro", "disk_size": 20}]},
    )
    assert aws["Instance class"] == "db.t3.medium"
    assert aws["Allocated storage"] == "100 GB"
    assert azure["SKU"] == "GP_Standard_D2s_v3" and azure["Storage"] == "32 GB"
    assert gcp["Tier"] == "db-f1-micro" and gcp["Disk size"] == "20 GB"


def test_autoscaling_detail_is_exposed():
    aws = extract_configuration(
        "aws_autoscaling_group", {"min_size": 1, "max_size": 4, "desired_capacity": 2}
    )
    gcp = extract_configuration(
        "google_compute_autoscaler",
        {"autoscaling_policy": [{"min_replicas": 1, "max_replicas": 4}]},
    )
    assert aws["Min size"] == "1" and aws["Max size"] == "4"
    assert gcp["Min replicas"] == "1" and gcp["Max replicas"] == "4"


def test_unknown_resource_type_returns_empty_without_raising():
    assert extract_configuration("totally_unknown_type", {"anything": 1}) == {}


def test_unmapped_resource_of_a_known_cloud_still_reports_location():
    config = extract_configuration("azurerm_brand_new_thing", {"location": "eastus"})
    assert config == {"Location": "eastus"}


def test_none_values_do_not_raise():
    assert extract_configuration("aws_instance", None) == {}


def test_adapter_routing_is_by_resource_type_prefix():
    assert adapter_for("aws_instance").cloud is Cloud.AWS
    assert adapter_for("azurerm_managed_disk").cloud is Cloud.AZURE
    assert adapter_for("google_compute_disk").cloud is Cloud.GCP
    assert adapter_for("mystery_resource") is None


# ---------------------------------------------------------------------------
# Terraform <-> Infracost join
# ---------------------------------------------------------------------------


def _cost(address, resource_type, cloud, new=Decimal("10"), prev=Decimal("0")):
    return ResourceCost(
        address=address,
        resource_type=resource_type,
        cloud=cloud,
        previous_monthly_cost=prev,
        new_monthly_cost=new,
        delta_monthly_cost=new - prev,
        confidence=CostConfidence.PRICED,
        action=Action.CREATE,
    )


def _change(address, resource_type, cloud, after=None, before=None, action=Action.CREATE):
    return ResourceChange(
        address=address,
        resource_type=resource_type,
        name=address.split(".")[-1],
        cloud=cloud,
        action=action,
        before=before or {},
        after=after or {},
    )


def _estimate(resources):
    return CostEstimate(
        currency="USD",
        estimator="infracost",
        trust=EstimatorTrust.AUTHORITATIVE,
        previous_monthly_cost=Decimal("0"),
        new_monthly_cost=Decimal("10"),
        incremental_monthly_cost=Decimal("10"),
        resources=resources,
    )


def _plan(changes):
    return NormalizedPlan(
        terraform_version="1.11.0", format_version="1.2", changes=changes, clouds=[]
    )


def test_join_matches_on_terraform_address():
    cost = _cost("azurerm_linux_virtual_machine.app", "azurerm_linux_virtual_machine", Cloud.AZURE)
    change = _change(
        "azurerm_linux_virtual_machine.app", "azurerm_linux_virtual_machine", Cloud.AZURE, AZURE_VM
    )
    views = join_estimate_with_plan(_estimate([cost]), _plan([change]))
    assert views[0].configuration["VM size"] == "Standard_B2s"
    assert views[0].service == "Virtual Machines"


def test_join_is_case_insensitive_on_address_only():
    cost = _cost("Module.App.aws_instance.Main", "aws_instance", Cloud.AWS)
    change = _change("module.app.aws_instance.main", "aws_instance", Cloud.AWS, AWS_VM)
    views = join_estimate_with_plan(_estimate([cost]), _plan([change]))
    assert views[0].configuration["Instance type"] == "t3.large"


def test_unmatched_priced_resource_still_reports_cost_without_configuration():
    cost = _cost("aws_instance.ghost", "aws_instance", Cloud.AWS)
    views = join_estimate_with_plan(_estimate([cost]), _plan([]))
    assert views[0].configuration == {}
    assert views[0].new_monthly_cost == Decimal("10")


def test_join_without_a_plan_does_not_raise():
    cost = _cost("aws_instance.a", "aws_instance", Cloud.AWS)
    views = join_estimate_with_plan(_estimate([cost]), None)
    assert views[0].has_configuration is False


def test_join_never_alters_cost_values():
    """The money must be byte-identical to the estimate's own values."""
    cost = _cost("aws_instance.a", "aws_instance", Cloud.AWS, new=Decimal("123.45"))
    change = _change("aws_instance.a", "aws_instance", Cloud.AWS, AWS_VM)
    view = build_view(cost, change)
    assert view.new_monthly_cost == cost.new_monthly_cost
    assert view.delta_monthly_cost == cost.delta_monthly_cost
    assert view.previous_monthly_cost == cost.previous_monthly_cost
    assert view.cost is cost


def test_before_after_is_captured_for_an_update():
    before = dict(AZURE_VM, size="Standard_B1s")
    change = _change(
        "azurerm_linux_virtual_machine.app",
        "azurerm_linux_virtual_machine",
        Cloud.AZURE,
        after=AZURE_VM,
        before=before,
        action=Action.UPDATE,
    )
    view = build_view(
        _cost("azurerm_linux_virtual_machine.app", "azurerm_linux_virtual_machine", Cloud.AZURE),
        change,
    )
    assert view.changed_fields["VM size"] == ("Standard_B1s", "Standard_B2s")
    assert view.configuration["VM size"] == "Standard_B2s"


def test_a_delete_reports_the_configuration_that_existed():
    change = _change(
        "google_compute_instance.app",
        "google_compute_instance",
        Cloud.GCP,
        after={},
        before=GCP_VM,
        action=Action.DELETE,
    )
    view = build_view(
        _cost("google_compute_instance.app", "google_compute_instance", Cloud.GCP), change
    )
    assert view.configuration["Machine type"] == "e2-small"


def test_view_serializes_without_losing_identity():
    change = _change("aws_instance.a", "aws_instance", Cloud.AWS, AWS_VM)
    payload = build_view(_cost("aws_instance.a", "aws_instance", Cloud.AWS), change).to_dict()
    assert payload["service"] == "EC2"
    assert payload["cloud"] == "aws"
    assert payload["configuration"]["Instance type"] == "t3.large"
