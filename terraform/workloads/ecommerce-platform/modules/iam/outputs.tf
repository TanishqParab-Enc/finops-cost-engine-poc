output "app_instance_profile_name" {
  description = "Instance profile attached to storefront instances."
  value       = aws_iam_instance_profile.app.name
}

output "worker_instance_profile_name" {
  description = "Instance profile attached to worker instances."
  value       = aws_iam_instance_profile.worker.name
}

output "app_role_arn" {
  description = "Storefront tier role ARN."
  value       = aws_iam_role.app.arn
}

output "worker_role_arn" {
  description = "Worker tier role ARN."
  value       = aws_iam_role.worker.arn
}
