output "app_log_group_arn" {
  description = "Storefront log group ARN, used to scope the storefront role."
  value       = aws_cloudwatch_log_group.app.arn
}

output "worker_log_group_arn" {
  description = "Worker log group ARN, used to scope the worker role."
  value       = aws_cloudwatch_log_group.worker.arn
}

output "app_log_group_name" {
  description = "Storefront log group name."
  value       = aws_cloudwatch_log_group.app.name
}

output "worker_log_group_name" {
  description = "Worker log group name."
  value       = aws_cloudwatch_log_group.worker.name
}
