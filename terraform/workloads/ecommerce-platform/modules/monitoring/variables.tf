variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "retention_days" {
  description = "CloudWatch Logs retention for both tiers."
  type        = number
}

variable "app_autoscaling_group_name" {
  description = "Storefront Auto Scaling group the CPU alarm watches."
  type        = string
}

variable "alb_arn_suffix" {
  description = "Load balancer ARN suffix the 5xx alarm watches."
  type        = string
}

variable "database_identifier" {
  description = "Order database identifier the CPU alarm watches."
  type        = string
}

variable "order_queue_name" {
  description = "Order queue the backlog alarm watches."
  type        = string
}

variable "order_dlq_name" {
  description = "Dead-letter queue the failure alarm watches."
  type        = string
}

variable "cache_replication_group_id" {
  description = "Redis replication group the eviction alarm watches."
  type        = string
}

variable "queue_depth_threshold" {
  description = "Visible order events that indicate the worker tier is falling behind."
  type        = number
}
