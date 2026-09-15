variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "retention_seconds" {
  description = "How long an unprocessed order event is retained."
  type        = number
}

variable "visibility_timeout_seconds" {
  description = "How long a claimed order event stays hidden from other workers."
  type        = number
  default     = 300
}

variable "max_receive_count" {
  description = "Deliveries attempted before an order event moves to the dead-letter queue."
  type        = number
}
