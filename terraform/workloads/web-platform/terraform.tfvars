# Committed baseline. A pull request that edits this file changes cloud cost,
# which is exactly what the FinOps gate compares against the base branch.
region             = "us-east-1"
environment        = "Dev"
application_name   = "webplatform"
availability_zones = ["us-east-1a", "us-east-1b"]

instance_type    = "t3.xlarge"
desired_capacity = 1
min_capacity     = 1
max_capacity     = 3
root_volume_size = 40

rds_instance_class = "db.t3.small"
rds_storage        = 50
rds_multi_az       = false

nat_gateway_count = 1
s3_storage_gb     = 20

cloudfront_enabled = true
dns_enabled        = true
log_retention_days = 30
