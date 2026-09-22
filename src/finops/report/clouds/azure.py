"""Azure resource-to-service and configuration mappings.

Replaces the previous `azurerm_x_y -> "X"` fallback, which classified
azurerm_linux_virtual_machine as "Linux" and azurerm_managed_disk as "Managed".
"""

from __future__ import annotations

from ..metadata import FieldSpec, count, gigabytes, plain

SERVICE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("azurerm_linux_virtual_machine_scale_set", "Virtual Machine Scale Sets"),
    ("azurerm_windows_virtual_machine_scale_set", "Virtual Machine Scale Sets"),
    ("azurerm_virtual_machine_scale_set", "Virtual Machine Scale Sets"),
    ("azurerm_linux_virtual_machine", "Virtual Machines"),
    ("azurerm_windows_virtual_machine", "Virtual Machines"),
    ("azurerm_virtual_machine_data_disk_attachment", "Managed Disks"),
    ("azurerm_virtual_machine", "Virtual Machines"),
    ("azurerm_managed_disk", "Managed Disks"),
    ("azurerm_snapshot", "Managed Disks"),
    ("azurerm_storage_account", "Storage"),
    ("azurerm_storage_container", "Storage"),
    ("azurerm_storage_share", "Storage"),
    ("azurerm_storage_", "Storage"),
    ("azurerm_postgresql_flexible_server", "PostgreSQL"),
    ("azurerm_postgresql", "PostgreSQL"),
    ("azurerm_mysql_flexible_server", "MySQL"),
    ("azurerm_mysql", "MySQL"),
    ("azurerm_mssql_managed_instance", "SQL Managed Instance"),
    ("azurerm_mssql", "SQL Database"),
    ("azurerm_sql", "SQL Database"),
    ("azurerm_cosmosdb", "Cosmos DB"),
    ("azurerm_redis", "Cache for Redis"),
    ("azurerm_application_gateway", "Application Gateway"),
    ("azurerm_lb", "Load Balancer"),
    ("azurerm_nat_gateway", "NAT Gateway"),
    ("azurerm_public_ip", "Public IP"),
    ("azurerm_virtual_network_gateway", "VPN Gateway"),
    ("azurerm_virtual_network_peering", "Virtual Network"),
    ("azurerm_virtual_network", "Virtual Network"),
    ("azurerm_subnet", "Virtual Network"),
    ("azurerm_network_security_group", "Virtual Network"),
    ("azurerm_network_security_rule", "Virtual Network"),
    ("azurerm_network_interface", "Virtual Network"),
    ("azurerm_private_endpoint", "Private Link"),
    ("azurerm_servicebus", "Service Bus"),
    ("azurerm_eventhub", "Event Hubs"),
    ("azurerm_eventgrid", "Event Grid"),
    ("azurerm_log_analytics", "Log Analytics"),
    ("azurerm_application_insights", "Application Insights"),
    ("azurerm_monitor", "Azure Monitor"),
    ("azurerm_key_vault", "Key Vault"),
    ("azurerm_container_registry", "Container Registry"),
    ("azurerm_kubernetes_cluster", "Kubernetes Service"),
    ("azurerm_container_app", "Container Apps"),
    ("azurerm_linux_function_app", "Functions"),
    ("azurerm_windows_function_app", "Functions"),
    ("azurerm_function_app", "Functions"),
    ("azurerm_service_plan", "App Service"),
    ("azurerm_app_service", "App Service"),
    ("azurerm_cdn", "CDN"),
    ("azurerm_user_assigned_identity", "Managed Identity"),
    ("azurerm_resource_group", "Resource Group"),
)

_LOCATION = FieldSpec("Location", ("location",))

_VM_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("VM size", ("size", "vm_size")),
    _LOCATION,
    FieldSpec("Zone", ("zone",)),
    FieldSpec(
        "Image",
        ("source_image_reference.0.offer", "source_image_id"),
    ),
    FieldSpec("Image SKU", ("source_image_reference.0.sku",)),
    FieldSpec("OS disk type", ("os_disk.0.storage_account_type",)),
    FieldSpec("OS disk size", ("os_disk.0.disk_size_gb",), gigabytes),
    FieldSpec("OS disk caching", ("os_disk.0.caching",)),
)

FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "azurerm_linux_virtual_machine": _VM_FIELDS,
    "azurerm_windows_virtual_machine": _VM_FIELDS,
    "azurerm_linux_virtual_machine_scale_set": (
        FieldSpec("VM size", ("sku", "size")),
        FieldSpec("Instances", ("instances",)),
        _LOCATION,
        FieldSpec("OS disk type", ("os_disk.0.storage_account_type",)),
    ),
    "azurerm_managed_disk": (
        FieldSpec("Disk size", ("disk_size_gb",), gigabytes),
        FieldSpec("Disk type", ("storage_account_type",)),
        FieldSpec("Tier", ("tier",)),
        FieldSpec("IOPS", ("disk_iops_read_write",)),
        FieldSpec("Throughput (MBps)", ("disk_mbps_read_write",)),
        _LOCATION,
        FieldSpec("Zone", ("zone",)),
    ),
    "azurerm_storage_account": (
        FieldSpec("Account tier", ("account_tier",)),
        FieldSpec("Replication", ("account_replication_type",)),
        FieldSpec("Kind", ("account_kind",)),
        FieldSpec("Access tier", ("access_tier",)),
        _LOCATION,
    ),
    "azurerm_postgresql_flexible_server": (
        FieldSpec("SKU", ("sku_name",)),
        FieldSpec("Version", ("version",)),
        FieldSpec("Storage", ("storage_mb",), lambda v: gigabytes(float(v) / 1024)),
        FieldSpec("Storage tier", ("storage_tier",)),
        FieldSpec("High availability", ("high_availability.0.mode",)),
        FieldSpec("Backup retention (days)", ("backup_retention_days",)),
        _LOCATION,
    ),
    "azurerm_mssql_database": (
        FieldSpec("SKU", ("sku_name",)),
        FieldSpec("Max size", ("max_size_gb",), gigabytes),
        FieldSpec("Redundancy", ("zone_redundant",), plain),
        FieldSpec("Read replicas", ("read_replica_count",)),
        FieldSpec("License type", ("license_type",)),
    ),
    "azurerm_redis_cache": (
        FieldSpec("SKU", ("sku_name",)),
        FieldSpec("Family", ("family",)),
        FieldSpec("Capacity", ("capacity",)),
        FieldSpec("Replicas per primary", ("replicas_per_primary",)),
        _LOCATION,
    ),
    "azurerm_lb": (
        FieldSpec("SKU", ("sku",)),
        FieldSpec("SKU tier", ("sku_tier",)),
        FieldSpec("Frontend configurations", ("frontend_ip_configuration",), count),
        _LOCATION,
    ),
    "azurerm_application_gateway": (
        FieldSpec("SKU", ("sku.0.name",)),
        FieldSpec("SKU tier", ("sku.0.tier",)),
        FieldSpec("Capacity", ("sku.0.capacity",)),
        _LOCATION,
    ),
    "azurerm_public_ip": (
        FieldSpec("SKU", ("sku",)),
        FieldSpec("Allocation", ("allocation_method",)),
        FieldSpec("IP version", ("ip_version",)),
        _LOCATION,
    ),
    "azurerm_nat_gateway": (
        FieldSpec("SKU", ("sku_name",)),
        FieldSpec("Idle timeout (min)", ("idle_timeout_in_minutes",)),
        _LOCATION,
    ),
    "azurerm_virtual_network": (
        FieldSpec("Address space", ("address_space",), lambda v: ", ".join(v)),
        _LOCATION,
    ),
    "azurerm_subnet": (
        FieldSpec("Address prefixes", ("address_prefixes",), lambda v: ", ".join(v)),
    ),
    "azurerm_network_security_group": (
        FieldSpec("Security rules", ("security_rule",), count),
        _LOCATION,
    ),
    "azurerm_network_interface": (
        FieldSpec("IP configurations", ("ip_configuration",), count),
        FieldSpec("Accelerated networking", ("accelerated_networking_enabled",), plain),
        _LOCATION,
    ),
    "azurerm_log_analytics_workspace": (
        FieldSpec("SKU", ("sku",)),
        FieldSpec("Retention (days)", ("retention_in_days",)),
        FieldSpec("Daily quota (GB)", ("daily_quota_gb",)),
        _LOCATION,
    ),
    "azurerm_key_vault": (
        FieldSpec("SKU", ("sku_name",)),
        _LOCATION,
    ),
    "azurerm_servicebus_namespace": (
        FieldSpec("SKU", ("sku",)),
        FieldSpec("Capacity", ("capacity",)),
        _LOCATION,
    ),
    "azurerm_service_plan": (
        FieldSpec("SKU", ("sku_name",)),
        FieldSpec("OS type", ("os_type",)),
        FieldSpec("Worker count", ("worker_count",)),
        _LOCATION,
    ),
    "azurerm_virtual_machine_data_disk_attachment": (
        FieldSpec("LUN", ("lun",)),
        FieldSpec("Caching", ("caching",)),
    ),
}

FALLBACK: tuple[FieldSpec, ...] = (_LOCATION,)
