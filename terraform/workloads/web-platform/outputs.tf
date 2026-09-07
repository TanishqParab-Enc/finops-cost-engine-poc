# Outputs are metadata only - they create no resource and carry no cost, so
# touching this file exercises the gate without moving the estimate.

output "vpc_id" {
  description = "VPC hosting the platform."
  value       = module.networking.vpc_id
}

output "alb_dns_name" {
  description = "Public DNS name of the load balancer."
  value       = module.alb.alb_dns_name
}

output "cloudfront_domain_name" {
  description = "CloudFront domain, null when the CDN is disabled."
  value       = module.cdn.distribution_domain_name
}

output "assets_bucket" {
  description = "S3 bucket holding static assets."
  value       = module.object_storage.bucket_id
}

output "database_endpoint" {
  description = "RDS endpoint."
  value       = module.database.db_endpoint
}

output "autoscaling_group_name" {
  description = "Web tier Auto Scaling group."
  value       = module.compute.autoscaling_group_name
}

output "cost_levers" {
  description = "The variables that materially move the monthly bill, echoed so a plan diff shows them in one place."
  value = {
    instance_type      = var.instance_type
    desired_capacity   = var.desired_capacity
    root_volume_size   = var.root_volume_size
    rds_instance_class = var.rds_instance_class
    rds_storage        = var.rds_storage
    rds_multi_az       = var.rds_multi_az
    nat_gateway_count  = var.nat_gateway_count
    s3_storage_gb      = var.s3_storage_gb
    cloudfront_enabled = var.cloudfront_enabled
  }
}
