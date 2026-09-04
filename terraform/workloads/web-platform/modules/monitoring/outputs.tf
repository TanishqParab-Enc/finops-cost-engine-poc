output "application_log_group_arn" {
  value = aws_cloudwatch_log_group.app.arn
}

output "application_log_group_name" {
  value = aws_cloudwatch_log_group.app.name
}

output "access_log_group_name" {
  value = aws_cloudwatch_log_group.access.name
}
