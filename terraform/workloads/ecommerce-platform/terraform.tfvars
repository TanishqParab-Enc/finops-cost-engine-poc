# Committed baseline for the e-commerce platform. A pull request that edits this
# file changes cloud cost, which is exactly what the shared FinOps gate prices
# against the currently deployed state.
region             = "us-east-1"
environment        = "Dev"
application_name   = "shopfront"
availability_zones = ["us-east-1a", "us-east-1b"]

# -- storefront tier --
app_instance_type    = "t3.large"
app_desired_capacity = 2
app_min_capacity     = 2
app_max_capacity     = 6
app_root_volume_size = 30

# -- worker tier --
worker_instance_type    = "t3.medium"
worker_desired_capacity = 1
worker_min_capacity     = 1
worker_max_capacity     = 4
worker_root_volume_size = 20

# -- data tier --
db_instance_class    = "db.t3.medium"
db_allocated_storage = 50
db_multi_az          = false
cache_node_type      = "cache.t3.medium"
cache_node_count     = 2

# -- edge and egress --
nat_gateway_count = 1
enable_cdn        = true
cdn_price_class   = "PriceClass_100"
enable_dns        = true
dns_zone_name     = "shopfront-poc.internal"
