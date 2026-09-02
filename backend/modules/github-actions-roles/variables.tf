variable "project_name" {
  description = "Project identifier used to derive role names."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod, ...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,20}$", var.environment))
    error_message = "environment must be lowercase alphanumeric with hyphens."
  }
}

variable "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider to trust."
  type        = string
}

# ---------------------------------------------------------------------------
# GitHub repository scoping
# ---------------------------------------------------------------------------
variable "github_owner" {
  description = "GitHub organization or user that owns the repository."
  type        = string

  validation {
    condition     = length(var.github_owner) > 0 && !strcontains(var.github_owner, "/")
    error_message = "github_owner must be a bare org or user name, without a slash."
  }
}

variable "github_repository" {
  description = "GitHub repository name, without the owner prefix."
  type        = string

  validation {
    condition     = length(var.github_repository) > 0 && !strcontains(var.github_repository, "/")
    error_message = "github_repository must be a bare repository name, without a slash."
  }
}

# GitHub's immutable OIDC subject claims embed numeric IDs. Get them with:
#   gh api /repos/<owner>/<repo> --jq '{owner: .owner.id, repo: .id}'
variable "github_owner_id" {
  description = "Numeric GitHub owner ID, used to trust immutable OIDC subjects. Null trusts only the classic subject form."
  type        = string
  default     = null
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID, used to trust immutable OIDC subjects. Null trusts only the classic subject form."
  type        = string
  default     = null
}

variable "github_environment_name" {
  description = "GitHub environment that gates the deploy role."
  type        = string
  default     = "production"
}

variable "additional_deploy_environments" {
  description = "Extra GitHub Actions environment names (besides github_environment_name) trusted to assume the deploy role."
  type        = list(string)
  default     = []
}

variable "allowed_branches" {
  description = "Branches whose push events may assume the plan role."
  type        = list(string)
  default     = ["main"]
}

variable "plan_subjects" {
  description = "Explicit OIDC subject claims for the plan role. Overrides the derived defaults."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.plan_subjects, "*")
    error_message = "A wildcard subject would let any repository assume this role."
  }
}

variable "deploy_subjects" {
  description = "Explicit OIDC subject claims for the deploy role. Overrides the derived defaults."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.deploy_subjects, "*")
    error_message = "A wildcard subject would let any repository assume this role."
  }
}

# ---------------------------------------------------------------------------
# Terraform state
# ---------------------------------------------------------------------------
variable "state_bucket_name" {
  description = "Name of the S3 bucket holding Terraform state."
  type        = string
}

variable "state_key_prefixes" {
  description = "Object key patterns within the state bucket this environment may access."
  type        = list(string)
}

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
variable "plan_read_policy_json" {
  description = "IAM policy JSON granting the read access terraform plan needs. Must not grant write access."
  type        = string
}

variable "deploy_write_policy_json" {
  description = "IAM policy JSON granting the write access terraform apply needs."
  type        = string
}

variable "plan_additional_policy_arns" {
  description = "Extra managed policy ARNs for the plan role. Avoid AdministratorAccess."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains([for a in var.plan_additional_policy_arns : endswith(a, "/AdministratorAccess")], true)
    error_message = "AdministratorAccess must not be attached to the plan role."
  }
}

variable "deploy_additional_policy_arns" {
  description = "Extra managed policy ARNs for the deploy role. Avoid AdministratorAccess."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains([for a in var.deploy_additional_policy_arns : endswith(a, "/AdministratorAccess")], true)
    error_message = "AdministratorAccess must not be attached to the deploy role."
  }
}

variable "max_session_duration" {
  description = "Maximum assumed-role session duration in seconds."
  type        = number
  default     = 3600

  validation {
    condition     = var.max_session_duration >= 900 && var.max_session_duration <= 43200
    error_message = "max_session_duration must be between 900 and 43200 seconds."
  }
}

variable "plan_role_name" {
  description = "Explicit plan role name. Defaults to <project>-<environment>-plan-role."
  type        = string
  default     = null
}

variable "deploy_role_name" {
  description = "Explicit deploy role name. Defaults to <project>-<environment>-deploy-role."
  type        = string
  default     = null
}

# ---------------------------------------------------------------------------
# Bedrock (AI explanation layer)
# ---------------------------------------------------------------------------
variable "enable_bedrock_access" {
  description = "Grant the plan role permission to invoke the configured Bedrock inference profile."
  type        = bool
  default     = true
}

variable "bedrock_inference_profile_arn" {
  description = "ARN of the Bedrock inference profile the application invokes. Get it with: aws bedrock get-inference-profile --inference-profile-identifier <id>."
  type        = string
  default     = null

  validation {
    condition     = var.bedrock_inference_profile_arn == null || can(regex("^arn:aws[a-z-]*:bedrock:", var.bedrock_inference_profile_arn))
    error_message = "bedrock_inference_profile_arn must be a Bedrock ARN."
  }
}

variable "bedrock_foundation_model_arns" {
  description = "Foundation model ARNs for EVERY region the inference profile routes to. AWS requires these alongside the profile ARN. Read them from the `models` field of `aws bedrock get-inference-profile`."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Additional tags merged onto every resource."
  type        = map(string)
  default     = {}
}
