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
  description = "Private data subnets the instance is placed in."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group restricting PostgreSQL to the app and worker tiers."
  type        = string
}

variable "engine_version" {
  description = "PostgreSQL engine version."
  type        = string
}

variable "parameter_group_family" {
  description = "Parameter group family matching the engine version."
  type        = string
  default     = "postgres16"
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
}

variable "allocated_storage" {
  description = "Allocated storage in GiB."
  type        = number
}

variable "max_allocated_storage" {
  description = "Upper bound for storage autoscaling."
  type        = number
  default     = 200
}

variable "storage_type" {
  description = "RDS storage type."
  type        = string
}

variable "multi_az" {
  description = "Run a standby in a second AZ."
  type        = bool
}

variable "backup_retention_days" {
  description = "Automated backup retention in days."
  type        = number
}
