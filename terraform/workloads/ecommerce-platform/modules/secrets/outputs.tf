output "secret_arn" {
  description = "Application config secret ARN, used to scope the tier IAM policies."
  value       = aws_secretsmanager_secret.app.arn
}

output "secret_name" {
  description = "Application config secret name."
  value       = aws_secretsmanager_secret.app.name
}
