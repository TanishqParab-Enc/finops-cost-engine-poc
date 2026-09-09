output "zone_id" {
  value = try(aws_route53_zone.main[0].zone_id, null)
}

output "record_name" {
  value = try(aws_route53_record.app[0].name, null)
}
