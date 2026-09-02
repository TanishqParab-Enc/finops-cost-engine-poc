variable "project_name" {
  description = "Project identifier used to derive resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$", var.project_name))
    error_message = "project_name must be lowercase alphanumeric with hyphens, 3-32 characters."
  }
}

variable "aws_account_id" {
  description = "AWS account ID, used to make the default bucket name globally unique."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}

variable "bucket_name" {
  description = "Explicit state bucket name. Defaults to <project_name>-tfstate-<account_id>."
  type        = string
  default     = null
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key ARN for state encryption. Null uses SSE-S3 (AES256)."
  type        = string
  default     = null
}

variable "noncurrent_version_retention_days" {
  description = "Days to retain non-current state versions before expiry."
  type        = number
  default     = 90

  validation {
    condition     = var.noncurrent_version_retention_days >= 30
    error_message = "Retain at least 30 days of state history to allow recovery."
  }
}

variable "enable_legacy_dynamodb_lock" {
  description = "DEPRECATED. Create a DynamoDB lock table for pre-1.10 backends. New environments should use S3 native locking (use_lockfile = true)."
  type        = bool
  default     = false
}

variable "legacy_dynamodb_table_name" {
  description = "Name for the deprecated DynamoDB lock table. Defaults to <bucket_name>-lock."
  type        = string
  default     = null
}

variable "tags" {
  description = "Additional tags merged onto every resource."
  type        = map(string)
  default     = {}
}
