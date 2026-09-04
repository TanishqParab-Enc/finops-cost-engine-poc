# Scenario 1 - small workload, incremental cost stays under the $100 threshold.
# Only the root volume grows (30 -> 40 GB).
instance_type    = "t3.large"
desired_capacity = 1
root_volume_size = 40

rds_instance_class = "db.t3.small"
rds_storage        = 50
rds_multi_az       = false

nat_gateway_count  = 1
s3_storage_gb      = 20
cloudfront_enabled = true
