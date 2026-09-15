output "primary_endpoint" {
  description = "Redis primary endpoint the storefront connects to."
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "replication_group_id" {
  description = "Replication group id, used as the CloudWatch alarm dimension."
  value       = aws_elasticache_replication_group.main.replication_group_id
}
