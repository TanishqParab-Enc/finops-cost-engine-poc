output "cdn_domain_name" {
  description = "CloudFront domain name. Empty when the edge tier is disabled."
  value       = var.enabled ? aws_cloudfront_distribution.main[0].domain_name : ""
}

output "storefront_fqdn" {
  description = "Public storefront hostname. Empty when DNS is disabled."
  value       = var.enable_dns ? aws_route53_record.storefront[0].fqdn : ""
}

output "zone_id" {
  description = "Hosted zone id. Empty when DNS is disabled."
  value       = var.enable_dns ? aws_route53_zone.main[0].zone_id : ""
}
