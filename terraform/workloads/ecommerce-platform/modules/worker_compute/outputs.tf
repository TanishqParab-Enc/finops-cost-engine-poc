output "autoscaling_group_name" {
  description = "Worker Auto Scaling group name, used as the CloudWatch alarm dimension."
  value       = aws_autoscaling_group.worker.name
}

output "launch_template_id" {
  description = "Worker launch template id."
  value       = aws_launch_template.worker.id
}
