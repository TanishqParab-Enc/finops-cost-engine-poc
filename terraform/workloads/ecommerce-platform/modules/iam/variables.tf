variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "asset_bucket_arn" {
  description = "Product-asset bucket ARN both tiers are scoped to."
  type        = string
}

variable "order_queue_arn" {
  description = "Order queue ARN. The storefront may only send; workers may only consume."
  type        = string
}

variable "order_dlq_arn" {
  description = "Dead-letter queue ARN workers may inspect."
  type        = string
}

variable "app_secret_arn" {
  description = "Application config secret ARN the storefront may read."
  type        = string
}

variable "app_log_group_name" {
  description = "Storefront log group name, so the role can write only its own logs."
  type        = string
}

variable "worker_log_group_name" {
  description = "Worker log group name, so the role can write only its own logs."
  type        = string
}
