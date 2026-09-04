# Scenario 7 - no cost change. Identical sizing to terraform.tfvars; only a
# non-cost-bearing value (log retention) differs.
instance_type    = "t3.large"
desired_capacity = 1
root_volume_size = 30

rds_instance_class = "db.t3.small"
rds_storage        = 50
rds_multi_az       = false

nat_gateway_count  = 1
s3_storage_gb      = 20
cloudfront_enabled = true
log_retention_days = 14
