output "vpc_id" {
  description = "VPC the whole workload runs in."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnets hosting the load balancer and NAT gateways."
  value       = aws_subnet.public[*].id
}

output "app_subnet_ids" {
  description = "Private subnets hosting the storefront and worker tiers."
  value       = aws_subnet.app[*].id
}

output "data_subnet_ids" {
  description = "Private subnets hosting RDS and ElastiCache."
  value       = aws_subnet.data[*].id
}

output "alb_security_group_id" {
  description = "Security group for the load balancer."
  value       = aws_security_group.alb.id
}

output "app_security_group_id" {
  description = "Security group for storefront instances."
  value       = aws_security_group.app.id
}

output "worker_security_group_id" {
  description = "Security group for worker instances."
  value       = aws_security_group.worker.id
}

output "database_security_group_id" {
  description = "Security group for the order database."
  value       = aws_security_group.database.id
}

output "cache_security_group_id" {
  description = "Security group for the Redis replication group."
  value       = aws_security_group.cache.id
}
