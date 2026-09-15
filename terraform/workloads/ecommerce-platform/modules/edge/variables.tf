variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "enabled" {
  description = "Create the CloudFront distribution."
  type        = bool
}

variable "price_class" {
  description = "CloudFront price class."
  type        = string
}

variable "alb_dns_name" {
  description = "Load balancer DNS name used as the dynamic origin."
  type        = string
}

variable "alb_zone_id" {
  description = "Load balancer hosted zone id, used when DNS aliases the ALB directly."
  type        = string
}

variable "asset_bucket_domain_name" {
  description = "Regional domain name of the product-asset bucket."
  type        = string
}

variable "enable_dns" {
  description = "Create the hosted zone and storefront record."
  type        = bool
}

variable "zone_name" {
  description = "Hosted zone name."
  type        = string
}
