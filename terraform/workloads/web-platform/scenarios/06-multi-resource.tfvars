# Scenario 6 - several levers move at once: bigger instances, more of them,
# a second NAT gateway, larger root volume and a bigger database.
instance_type    = "m5.2xlarge"
desired_capacity = 3
min_capacity     = 3
max_capacity     = 6
root_volume_size = 100

rds_instance_class = "db.m5.large"
rds_storage        = 200
rds_multi_az       = true

nat_gateway_count  = 2
s3_storage_gb      = 20
cloudfront_enabled = true
