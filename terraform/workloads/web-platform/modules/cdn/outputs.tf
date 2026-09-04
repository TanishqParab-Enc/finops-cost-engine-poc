output "distribution_id" {
  value = try(aws_cloudfront_distribution.main[0].id, null)
}

output "distribution_domain_name" {
  value = try(aws_cloudfront_distribution.main[0].domain_name, null)
}

output "distribution_hosted_zone_id" {
  value = try(aws_cloudfront_distribution.main[0].hosted_zone_id, null)
}
