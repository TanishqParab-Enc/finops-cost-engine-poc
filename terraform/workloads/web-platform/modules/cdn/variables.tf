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

variable "price_class" {
  type = string
}

variable "assets_bucket_domain_name" {
  type = string
}

variable "alb_dns_name" {
  type = string
}
