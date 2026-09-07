variable "name_prefix" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "enabled" {
  type = bool
}

variable "zone_name" {
  type = string
}

variable "cdn_enabled" {
  type = bool
}

variable "cdn_domain_name" {
  type    = string
  default = null
}

variable "cdn_hosted_zone_id" {
  type    = string
  default = null
}

variable "alb_dns_name" {
  type = string
}

variable "alb_zone_id" {
  type = string
}
