output "autoscaling_group_name" {
  description = "Storefront Auto Scaling group name, used as the CloudWatch alarm dimension."
  value       = aws_autoscaling_group.storefront.name
}

output "launch_template_id" {
  description = "Storefront launch template id."
  value       = aws_launch_template.storefront.id
}
