# Scenario 5 - ASG capacity increase, 1 -> 3 instances.
instance_type    = "t3.large"
desired_capacity = 3
min_capacity     = 3
max_capacity     = 6
root_volume_size = 30

rds_instance_class = "db.t3.small"
rds_storage        = 50
rds_multi_az       = false

nat_gateway_count  = 1
s3_storage_gb      = 20
cloudfront_enabled = true
