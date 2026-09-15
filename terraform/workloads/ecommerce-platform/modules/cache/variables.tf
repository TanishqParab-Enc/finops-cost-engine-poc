variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "data_subnet_ids" {
  description = "Private data subnets the cache nodes are placed in."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group restricting Redis to the storefront tier."
  type        = string
}

variable "node_type" {
  description = "ElastiCache node type."
  type        = string
}

variable "node_count" {
  description = "Cache clusters in the replication group. 1 = primary only."
  type        = number
}

variable "engine_version" {
  description = "Redis engine version."
  type        = string
  default     = "7.1"
}

variable "parameter_group_name" {
  description = "Default parameter group matching the engine version."
  type        = string
  default     = "default.redis7"
}

variable "snapshot_retention_days" {
  description = "Days of automatic snapshots to keep."
  type        = number
  default     = 1
}
