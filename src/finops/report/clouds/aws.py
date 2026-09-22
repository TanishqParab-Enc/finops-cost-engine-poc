"""AWS resource-to-service and configuration mappings.

SERVICE_PREFIXES preserves the existing AWS classification verbatim; changing
a label here changes an existing AWS report, so it is deliberately a move, not
a rewrite.
"""

from __future__ import annotations

from ..metadata import FieldSpec, count, csv, gigabytes, plain

# Order matters: the first matching prefix wins, so specific types precede
# broader ones (aws_db_instance before aws_db_).
SERVICE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("aws_autoscaling_group", "EC2"),
    ("aws_launch_template", "EC2"),
    ("aws_launch_configuration", "EC2"),
    ("aws_instance", "EC2"),
    ("aws_spot_instance_request", "EC2"),
    ("aws_ebs_volume", "EBS"),
    ("aws_ebs_snapshot", "EBS"),
    ("aws_db_instance", "RDS"),
    ("aws_rds_cluster", "RDS"),
    ("aws_db_", "RDS"),
    ("aws_elasticache", "ElastiCache"),
    ("aws_dynamodb", "DynamoDB"),
    ("aws_s3_", "S3"),
    ("aws_lb", "Load Balancing"),
    ("aws_alb", "Load Balancing"),
    ("aws_elb", "Load Balancing"),
    ("aws_nat_gateway", "NAT Gateway"),
    ("aws_eip", "Elastic IP"),
    ("aws_vpn", "VPN"),
    ("aws_vpc_endpoint", "VPC Endpoint"),
    ("aws_cloudfront", "CloudFront"),
    ("aws_route53", "Route 53"),
    ("aws_cloudwatch", "CloudWatch"),
    ("aws_lambda", "Lambda"),
    ("aws_ecs", "ECS"),
    ("aws_eks", "EKS"),
    ("aws_sqs", "SQS"),
    ("aws_sns", "SNS"),
    ("aws_kms", "KMS"),
    ("aws_secretsmanager", "Secrets Manager"),
    ("aws_apigateway", "API Gateway"),
    ("aws_api_gateway", "API Gateway"),
    ("aws_efs", "EFS"),
    ("aws_fsx", "FSx"),
)

_REGION = FieldSpec("Region", ("region", "availability_zone"))

FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    "aws_instance": (
        FieldSpec("Instance type", ("instance_type",)),
        _REGION,
        FieldSpec("AMI", ("ami",)),
        FieldSpec("Tenancy", ("tenancy",)),
        FieldSpec(
            "Root disk",
            ("root_block_device.0.volume_size",),
            gigabytes,
        ),
        FieldSpec("Root disk type", ("root_block_device.0.volume_type",)),
        FieldSpec("Root disk IOPS", ("root_block_device.0.iops",)),
        FieldSpec("Extra EBS volumes", ("ebs_block_device",), count),
    ),
    "aws_autoscaling_group": (
        FieldSpec("Min size", ("min_size",)),
        FieldSpec("Max size", ("max_size",)),
        FieldSpec("Desired capacity", ("desired_capacity",)),
        FieldSpec("Availability zones", ("availability_zones",), csv),
        _REGION,
    ),
    "aws_launch_template": (
        FieldSpec("Instance type", ("instance_type",)),
        FieldSpec("Image", ("image_id",)),
        _REGION,
    ),
    "aws_ebs_volume": (
        FieldSpec("Size", ("size",), gigabytes),
        FieldSpec("Volume type", ("type",)),
        FieldSpec("IOPS", ("iops",)),
        FieldSpec("Throughput", ("throughput",)),
        FieldSpec("Availability zone", ("availability_zone",)),
    ),
    "aws_db_instance": (
        FieldSpec("Engine", ("engine",)),
        FieldSpec("Engine version", ("engine_version",)),
        FieldSpec("Instance class", ("instance_class",)),
        FieldSpec("Allocated storage", ("allocated_storage",), gigabytes),
        FieldSpec("Max allocated storage", ("max_allocated_storage",), gigabytes),
        FieldSpec("Storage type", ("storage_type",)),
        FieldSpec("IOPS", ("iops",)),
        FieldSpec("Multi-AZ", ("multi_az",), plain),
        FieldSpec("Backup retention", ("backup_retention_period",)),
        _REGION,
    ),
    "aws_rds_cluster": (
        FieldSpec("Engine", ("engine",)),
        FieldSpec("Engine version", ("engine_version",)),
        FieldSpec("Engine mode", ("engine_mode",)),
        FieldSpec("Min capacity", ("serverlessv2_scaling_configuration.0.min_capacity",)),
        FieldSpec("Max capacity", ("serverlessv2_scaling_configuration.0.max_capacity",)),
        FieldSpec("Backup retention", ("backup_retention_period",)),
        _REGION,
    ),
    "aws_rds_cluster_instance": (
        FieldSpec("Instance class", ("instance_class",)),
        FieldSpec("Engine", ("engine",)),
        _REGION,
    ),
    "aws_elasticache_cluster": (
        FieldSpec("Engine", ("engine",)),
        FieldSpec("Engine version", ("engine_version",)),
        FieldSpec("Node type", ("node_type",)),
        FieldSpec("Nodes", ("num_cache_nodes",)),
        _REGION,
    ),
    "aws_elasticache_replication_group": (
        FieldSpec("Engine", ("engine",)),
        FieldSpec("Node type", ("node_type",)),
        FieldSpec("Node groups", ("num_node_groups",)),
        FieldSpec("Replicas per node group", ("replicas_per_node_group",)),
        FieldSpec("Cache clusters", ("num_cache_clusters",)),
        FieldSpec("Multi-AZ", ("multi_az_enabled",), plain),
        _REGION,
    ),
    "aws_s3_bucket": (
        FieldSpec("Bucket", ("bucket",)),
        _REGION,
    ),
    "aws_lb": (
        FieldSpec("Load balancer type", ("load_balancer_type",)),
        FieldSpec("Scheme", ("internal",), lambda v: "internal" if v else "internet-facing"),
        FieldSpec("Subnets", ("subnets",), count),
        _REGION,
    ),
    "aws_nat_gateway": (
        FieldSpec("Connectivity", ("connectivity_type",)),
        _REGION,
    ),
    "aws_eip": (
        FieldSpec("Domain", ("domain",)),
        _REGION,
    ),
    "aws_cloudwatch_log_group": (
        FieldSpec("Retention (days)", ("retention_in_days",)),
        _REGION,
    ),
    "aws_sqs_queue": (
        FieldSpec("FIFO", ("fifo_queue",), plain),
        FieldSpec("Message retention (s)", ("message_retention_seconds",)),
        _REGION,
    ),
    "aws_secretsmanager_secret": (
        FieldSpec("Recovery window (days)", ("recovery_window_in_days",)),
        _REGION,
    ),
    "aws_dynamodb_table": (
        FieldSpec("Billing mode", ("billing_mode",)),
        FieldSpec("Read capacity", ("read_capacity",)),
        FieldSpec("Write capacity", ("write_capacity",)),
        _REGION,
    ),
}

# Applied when a type has no explicit mapping, so an unmapped AWS resource
# still reports where it lives rather than nothing at all.
FALLBACK: tuple[FieldSpec, ...] = (_REGION,)
