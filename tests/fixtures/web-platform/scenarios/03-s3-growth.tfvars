# Scenario 3 - S3 storage increase, 20 GB -> 500 GB.
# S3 is usage-priced: scenarios/03-s3-growth.usage.yml must be passed with
# --usage-file for this to change the estimate.
instance_type    = "t3.large"
desired_capacity = 1
root_volume_size = 30

rds_instance_class = "db.t3.small"
rds_storage        = 50
rds_multi_az       = false

nat_gateway_count  = 1
s3_storage_gb      = 500
cloudfront_enabled = true
