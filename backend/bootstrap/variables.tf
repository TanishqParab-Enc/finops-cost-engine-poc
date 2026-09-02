variable "project_name" {
  description = "Project identifier used to derive resource names."
  type        = string
  default     = "finops-poc"
}

variable "aws_region" {
  description = "Region for the Terraform state bucket."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Explicit state bucket name. Defaults to <project_name>-tfstate-<account_id>."
  type        = string
  default     = null
}

variable "noncurrent_version_retention_days" {
  description = "Days to retain non-current state versions."
  type        = number
  default     = 90
}

variable "enable_legacy_dynamodb_lock" {
  description = "DEPRECATED. Only enable when migrating an environment that still uses DynamoDB locking."
  type        = bool
  default     = false
}
