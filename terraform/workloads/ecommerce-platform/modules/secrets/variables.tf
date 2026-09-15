variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "cache_endpoint" {
  description = "Redis primary endpoint published to the application."
  type        = string
}

variable "order_queue_url" {
  description = "Order queue URL published to the application."
  type        = string
}

variable "asset_bucket" {
  description = "Product-asset bucket name published to the application."
  type        = string
}
