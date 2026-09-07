# Scenario 4 - RDS scaling: larger class, more storage, multi-AZ.
instance_type    = "t3.large"
desired_capacity = 1
root_volume_size = 30

rds_instance_class = "db.m5.xlarge"
rds_storage        = 500
rds_multi_az       = true

nat_gateway_count  = 1
s3_storage_gb      = 20
cloudfront_enabled = true
