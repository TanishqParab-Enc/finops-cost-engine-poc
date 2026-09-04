# Scenario 2 - large EC2 change. t3.large -> m5.4xlarge, clearly over $100.
instance_type    = "m5.4xlarge"
desired_capacity = 1
root_volume_size = 30

rds_instance_class = "db.t3.small"
rds_storage        = 50
rds_multi_az       = false

nat_gateway_count  = 1
s3_storage_gb      = 20
cloudfront_enabled = true
