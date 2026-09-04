# Scenario 8 - resource removal. CloudFront and the NAT gateway are dropped,
# so the incremental cost is negative.
instance_type    = "t3.large"
desired_capacity = 1
root_volume_size = 30

rds_instance_class = "db.t3.small"
rds_storage        = 50
rds_multi_az       = false

nat_gateway_count  = 0
s3_storage_gb      = 20
cloudfront_enabled = false
dns_enabled        = false
