resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.name_prefix}-cache-subnets"
  subnet_ids = var.data_subnet_ids

  tags = merge(var.tags, { Name = "${var.name_prefix}-cache-subnets" })
}

# Session and catalogue cache for the storefront. node_count = 1 is a single
# primary; 2 adds a replica in the second AZ and enables automatic failover.
resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${var.name_prefix}-cache"
  description          = "Storefront session and catalogue cache"

  engine         = "redis"
  engine_version = var.engine_version
  node_type      = var.node_type
  port           = 6379

  num_cache_clusters         = var.node_count
  automatic_failover_enabled = var.node_count > 1
  multi_az_enabled           = var.node_count > 1

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [var.security_group_id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  parameter_group_name     = var.parameter_group_name
  snapshot_retention_limit = var.snapshot_retention_days
  maintenance_window       = "sun:05:00-sun:06:00"
  apply_immediately        = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-cache" })
}
