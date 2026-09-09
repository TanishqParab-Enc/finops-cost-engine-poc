# A hosted zone bills a flat monthly charge per zone, so this is a small but
# real line item in the Infracost breakdown.
resource "aws_route53_zone" "main" {
  count = var.enabled ? 1 : 0

  name    = var.zone_name
  comment = "${var.name_prefix} web platform (test workload - not delegated)"

  tags = var.tags
}

resource "aws_route53_record" "app" {
  count = var.enabled ? 1 : 0

  zone_id = aws_route53_zone.main[0].zone_id
  name    = var.zone_name
  type    = "A"

  alias {
    name                   = var.cdn_enabled ? var.cdn_domain_name : var.alb_dns_name
    zone_id                = var.cdn_enabled ? var.cdn_hosted_zone_id : var.alb_zone_id
    evaluate_target_health = false
  }
}
