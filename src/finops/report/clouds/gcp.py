"""GCP resource-to-service and configuration mappings.

Replaces the previous `google_x_y -> "X"` fallback, which classified every
google_compute_* resource as "Compute" regardless of what it actually was.
"""

from __future__ import annotations

from ..metadata import FieldSpec, count, gigabytes, plain

SERVICE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("google_compute_instance_template", "Compute Engine"),
    ("google_compute_instance_group_manager", "Compute Engine"),
    ("google_compute_region_instance_group_manager", "Compute Engine"),
    ("google_compute_autoscaler", "Compute Engine"),
    ("google_compute_region_autoscaler", "Compute Engine"),
    ("google_compute_instance", "Compute Engine"),
    ("google_compute_disk", "Persistent Disk"),
    ("google_compute_region_disk", "Persistent Disk"),
    ("google_compute_snapshot", "Persistent Disk"),
    ("google_compute_image", "Compute Engine"),
    ("google_compute_attached_disk", "Persistent Disk"),
    ("google_compute_address", "Cloud IP"),
    ("google_compute_global_address", "Cloud IP"),
    ("google_compute_router_nat", "Cloud NAT"),
    ("google_compute_router", "Cloud Router"),
    ("google_compute_vpn", "Cloud VPN"),
    ("google_compute_forwarding_rule", "Cloud Load Balancing"),
    ("google_compute_global_forwarding_rule", "Cloud Load Balancing"),
    ("google_compute_target_pool", "Cloud Load Balancing"),
    ("google_compute_backend_service", "Cloud Load Balancing"),
    ("google_compute_url_map", "Cloud Load Balancing"),
    ("google_compute_firewall", "VPC Network"),
    ("google_compute_subnetwork", "VPC Network"),
    ("google_compute_network", "VPC Network"),
    ("google_storage_bucket", "Cloud Storage"),
    ("google_storage_", "Cloud Storage"),
    ("google_sql_database_instance", "Cloud SQL"),
    ("google_sql_", "Cloud SQL"),
    ("google_redis_instance", "Memorystore"),
    ("google_bigtable", "Bigtable"),
    ("google_bigquery", "BigQuery"),
    ("google_pubsub", "Pub/Sub"),
    ("google_cloudfunctions", "Cloud Functions"),
    ("google_cloud_run", "Cloud Run"),
    ("google_container_cluster", "Kubernetes Engine"),
    ("google_container_node_pool", "Kubernetes Engine"),
    ("google_logging", "Cloud Logging"),
    ("google_monitoring", "Cloud Monitoring"),
    ("google_secret_manager", "Secret Manager"),
    ("google_kms", "Cloud KMS"),
    ("google_artifact_registry", "Artifact Registry"),
    ("google_service_account", "IAM"),
    ("google_project_iam", "IAM"),
)

_LOCATION = FieldSpec("Location", ("zone", "region", "location"))

FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "google_compute_instance": (
        FieldSpec("Machine type", ("machine_type",)),
        _LOCATION,
        FieldSpec("Image", ("boot_disk.0.initialize_params.0.image",)),
        FieldSpec(
            "Boot disk",
            ("boot_disk.0.initialize_params.0.size",),
            gigabytes,
        ),
        FieldSpec("Boot disk type", ("boot_disk.0.initialize_params.0.type",)),
        FieldSpec("Attached disks", ("attached_disk",), count),
        FieldSpec("Preemptible", ("scheduling.0.preemptible",), plain),
        FieldSpec("Provisioning model", ("scheduling.0.provisioning_model",)),
    ),
    "google_compute_instance_template": (
        FieldSpec("Machine type", ("machine_type",)),
        FieldSpec("Region", ("region",)),
        FieldSpec("Boot disk", ("disk.0.disk_size_gb",), gigabytes),
        FieldSpec("Boot disk type", ("disk.0.disk_type",)),
    ),
    "google_compute_instance_group_manager": (
        FieldSpec("Target size", ("target_size",)),
        FieldSpec("Zone", ("zone",)),
    ),
    "google_compute_autoscaler": (
        FieldSpec("Min replicas", ("autoscaling_policy.0.min_replicas",)),
        FieldSpec("Max replicas", ("autoscaling_policy.0.max_replicas",)),
        FieldSpec("Zone", ("zone",)),
    ),
    "google_compute_disk": (
        FieldSpec("Disk size", ("size",), gigabytes),
        FieldSpec("Disk type", ("type",)),
        _LOCATION,
        FieldSpec("Provisioned IOPS", ("provisioned_iops",)),
        FieldSpec("Provisioned throughput", ("provisioned_throughput",)),
    ),
    "google_compute_attached_disk": (
        FieldSpec("Device name", ("device_name",)),
        FieldSpec("Mode", ("mode",)),
        FieldSpec("Zone", ("zone",)),
    ),
    "google_storage_bucket": (
        FieldSpec("Storage class", ("storage_class",)),
        FieldSpec("Location", ("location",)),
        FieldSpec("Versioning", ("versioning.0.enabled",), plain),
        FieldSpec("Lifecycle rules", ("lifecycle_rule",), count),
        FieldSpec("Uniform access", ("uniform_bucket_level_access",), plain),
    ),
    "google_sql_database_instance": (
        FieldSpec("Database version", ("database_version",)),
        FieldSpec("Tier", ("settings.0.tier",)),
        FieldSpec("Availability type", ("settings.0.availability_type",)),
        FieldSpec("Disk size", ("settings.0.disk_size",), gigabytes),
        FieldSpec("Disk type", ("settings.0.disk_type",)),
        FieldSpec("Disk autoresize", ("settings.0.disk_autoresize",), plain),
        FieldSpec("Region", ("region",)),
    ),
    "google_redis_instance": (
        FieldSpec("Tier", ("tier",)),
        FieldSpec("Memory size", ("memory_size_gb",), gigabytes),
        FieldSpec("Replicas", ("replica_count",)),
        FieldSpec("Redis version", ("redis_version",)),
        FieldSpec("Region", ("region",)),
    ),
    "google_compute_network": (
        FieldSpec("Auto subnets", ("auto_create_subnetworks",), plain),
        FieldSpec("Routing mode", ("routing_mode",)),
    ),
    "google_compute_subnetwork": (
        FieldSpec("IP range", ("ip_cidr_range",)),
        FieldSpec("Region", ("region",)),
        FieldSpec("Private Google access", ("private_ip_google_access",), plain),
    ),
    "google_compute_firewall": (
        FieldSpec("Direction", ("direction",)),
        FieldSpec("Allow rules", ("allow",), count),
        FieldSpec("Deny rules", ("deny",), count),
        FieldSpec("Source ranges", ("source_ranges",), lambda v: ", ".join(v)),
    ),
    "google_compute_address": (
        FieldSpec("Address type", ("address_type",)),
        FieldSpec("Network tier", ("network_tier",)),
        FieldSpec("Region", ("region",)),
    ),
    "google_compute_router_nat": (
        FieldSpec("NAT IP allocation", ("nat_ip_allocate_option",)),
        FieldSpec("Source subnetworks", ("source_subnetwork_ip_ranges_to_nat",)),
        FieldSpec("Region", ("region",)),
    ),
    "google_compute_forwarding_rule": (
        FieldSpec("Scheme", ("load_balancing_scheme",)),
        FieldSpec("Protocol", ("ip_protocol",)),
        FieldSpec("Region", ("region",)),
    ),
    "google_container_cluster": (
        FieldSpec("Initial node count", ("initial_node_count",)),
        FieldSpec("Location", ("location",)),
        FieldSpec("Release channel", ("release_channel.0.channel",)),
    ),
    "google_container_node_pool": (
        FieldSpec("Node count", ("node_count",)),
        FieldSpec("Machine type", ("node_config.0.machine_type",)),
        FieldSpec("Disk size", ("node_config.0.disk_size_gb",), gigabytes),
        FieldSpec("Disk type", ("node_config.0.disk_type",)),
        FieldSpec("Preemptible", ("node_config.0.preemptible",), plain),
    ),
    "google_pubsub_topic": (
        FieldSpec("Message retention", ("message_retention_duration",)),
    ),
    "google_pubsub_subscription": (
        FieldSpec("Ack deadline (s)", ("ack_deadline_seconds",)),
        FieldSpec("Message retention", ("message_retention_duration",)),
    ),
    "google_logging_project_bucket_config": (
        FieldSpec("Retention (days)", ("retention_days",)),
        FieldSpec("Location", ("location",)),
    ),
    "google_service_account": (
        FieldSpec("Account ID", ("account_id",)),
    ),
}

FALLBACK: tuple[FieldSpec, ...] = (_LOCATION,)
