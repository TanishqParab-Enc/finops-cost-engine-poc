output "endpoint" {
  description = "Order database connection endpoint."
  value       = aws_db_instance.main.endpoint
}

output "identifier" {
  description = "Instance identifier, used as the CloudWatch alarm dimension."
  value       = aws_db_instance.main.identifier
}

output "master_secret_arn" {
  description = "ARN of the RDS-managed master credential secret. Empty if RDS has not yet created it."
  value       = try(aws_db_instance.main.master_user_secret[0].secret_arn, "")
}
