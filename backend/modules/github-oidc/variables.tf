variable "project_name" {
  description = "Project identifier used for tagging."
  type        = string
}

variable "create_provider" {
  description = "Create the OIDC provider. Set false to reuse an existing one via existing_provider_arn."
  type        = bool
  default     = true
}

variable "existing_provider_arn" {
  description = "ARN of an existing GitHub OIDC provider to reuse. When set, no provider is created."
  type        = string
  default     = null

  validation {
    condition     = var.existing_provider_arn == null || can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:oidc-provider/", var.existing_provider_arn))
    error_message = "existing_provider_arn must be a valid IAM OIDC provider ARN."
  }
}

# IAM validates the GitHub OIDC provider against its published certificate
# chain, so these are a formality; kept configurable for air-gapped accounts.
variable "thumbprint_list" {
  description = "Certificate thumbprints for the GitHub OIDC endpoint."
  type        = list(string)
  default = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

variable "tags" {
  description = "Additional tags merged onto the provider."
  type        = map(string)
  default     = {}
}
