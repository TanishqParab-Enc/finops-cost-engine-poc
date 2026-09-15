output "storefront_url" {
  description = "Public entry point for customers."
  value       = module.edge.storefront_fqdn != "" ? "https://${module.edge.storefront_fqdn}" : "http://${module.alb.dns_name}"
}

output "alb_dns_name" {
  description = "Load balancer DNS name."
  value       = module.alb.dns_name
}

output "cdn_domain_name" {
  description = "CloudFront domain name, empty when the edge tier is disabled."
  value       = module.edge.cdn_domain_name
}

output "vpc_id" {
  description = "VPC the workload runs in."
  value       = module.networking.vpc_id
}

output "database_endpoint" {
  description = "Order database endpoint."
  value       = module.database.endpoint
  sensitive   = true
}

output "cache_endpoint" {
  description = "Redis primary endpoint."
  value       = module.cache.primary_endpoint
  sensitive   = true
}

output "order_queue_url" {
  description = "Queue the storefront publishes orders to."
  value       = module.messaging.queue_url
}

output "app_secret_name" {
  description = "Secrets Manager entry holding storefront runtime configuration."
  value       = module.secrets.secret_name
}

# The knobs that actually move the monthly bill. Surfaced as a single output so
# a reviewer can see, in the plan diff, exactly which cost drivers a change
# touched - the shared FinOps gate prices the change independently.
output "cost_levers" {
  description = "Configuration values with a direct, material effect on monthly cost."
  value = {
    app_instance_type       = var.app_instance_type
    app_desired_capacity    = var.app_desired_capacity
    worker_instance_type    = var.worker_instance_type
    worker_desired_capacity = var.worker_desired_capacity
    db_instance_class       = var.db_instance_class
    db_allocated_storage    = var.db_allocated_storage
    db_multi_az             = var.db_multi_az
    cache_node_type         = var.cache_node_type
    cache_node_count        = var.cache_node_count
    nat_gateway_count       = var.nat_gateway_count
    enable_cdn              = var.enable_cdn
    cdn_price_class         = var.cdn_price_class
  }
}
