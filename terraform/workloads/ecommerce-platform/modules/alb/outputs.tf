output "dns_name" {
  description = "Public DNS name of the load balancer, used as the CloudFront origin."
  value       = aws_lb.main.dns_name
}

output "zone_id" {
  description = "Hosted zone id of the load balancer, for alias records."
  value       = aws_lb.main.zone_id
}

output "target_group_arn" {
  description = "Target group the storefront Auto Scaling group registers with."
  value       = aws_lb_target_group.storefront.arn
}

output "arn_suffix" {
  description = "Load balancer ARN suffix, used as the CloudWatch alarm dimension."
  value       = aws_lb.main.arn_suffix
}
