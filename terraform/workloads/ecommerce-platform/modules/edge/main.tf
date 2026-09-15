# Two origins: dynamic storefront traffic goes to the ALB, product imagery is
# served straight from S3 so it never touches an instance.
resource "aws_cloudfront_origin_access_control" "assets" {
  count = var.enabled ? 1 : 0

  name                              = "${var.name_prefix}-assets-oac"
  description                       = "Signed access from CloudFront to the product-asset bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "main" {
  count = var.enabled ? 1 : 0

  enabled         = true
  comment         = "${var.name_prefix} storefront edge"
  price_class     = var.price_class
  is_ipv6_enabled = true

  origin {
    origin_id   = "storefront-alb"
    domain_name = var.alb_dns_name

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  origin {
    origin_id                = "product-assets"
    domain_name              = var.asset_bucket_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.assets[0].id
  }

  default_cache_behavior {
    target_origin_id       = "storefront-alb"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = true
      headers      = ["Host", "Origin"]

      cookies {
        forward = "all"
      }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  # Catalogue imagery is immutable once published, so it caches hard.
  ordered_cache_behavior {
    path_pattern           = "/assets/*"
    target_origin_id       = "product-assets"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 86400
    max_ttl     = 31536000
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-cdn" })
}

resource "aws_route53_zone" "main" {
  count = var.enable_dns ? 1 : 0

  name    = var.zone_name
  comment = "Storefront zone for ${var.name_prefix}"

  tags = merge(var.tags, { Name = "${var.name_prefix}-zone" })
}

# Points at CloudFront when the edge is enabled, otherwise straight at the ALB,
# so disabling the CDN leaves a working storefront rather than a broken record.
resource "aws_route53_record" "storefront" {
  count = var.enable_dns ? 1 : 0

  zone_id = aws_route53_zone.main[0].zone_id
  name    = "shop.${var.zone_name}"
  type    = "A"

  alias {
    name    = var.enabled ? aws_cloudfront_distribution.main[0].domain_name : var.alb_dns_name
    zone_id = var.enabled ? aws_cloudfront_distribution.main[0].hosted_zone_id : var.alb_zone_id

    evaluate_target_health = false
  }
}
