variable "project_name" {
  description = "Project identifier used to derive all resource names."
  type        = string
  default     = "finops-poc"
}

variable "environment" {
  description = "Environment name (dev, staging, prod, qa, ...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,20}$", var.environment))
    error_message = "environment must be lowercase alphanumeric with hyphens."
  }
}

variable "aws_region" {
  description = "AWS region this environment deploys into."
  type        = string
}

# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
variable "github_owner" {
  description = "GitHub organization or user that owns the repository."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository name, without the owner prefix."
  type        = string
}

# GitHub's immutable OIDC subject claims embed numeric IDs. Get them with:
#   gh api /repos/<owner>/<repo> --jq '{owner: .owner.id, repo: .id}'
variable "github_owner_id" {
  description = "Numeric GitHub owner ID, used to trust immutable OIDC subjects."
  type        = string
  default     = null
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID, used to trust immutable OIDC subjects."
  type        = string
  default     = null
}

variable "github_environment_name" {
  description = "GitHub Actions environment gating deployments. Used to scope the deploy role's OIDC trust subject."
  type        = string
  default     = "production"
}

variable "allowed_branches" {
  description = "Branches whose pushes may assume the plan role."
  type        = list(string)
  default     = ["main"]
}

# ---------------------------------------------------------------------------
# OIDC
# ---------------------------------------------------------------------------
variable "create_oidc_provider" {
  description = "Create the GitHub OIDC provider. Only one may exist per account, so set false in every environment after the first."
  type        = bool
  default     = false
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing GitHub OIDC provider to reuse."
  type        = string
  default     = null
}

# ---------------------------------------------------------------------------
# Terraform state
# ---------------------------------------------------------------------------
variable "state_bucket_name" {
  description = "Name of the shared Terraform state bucket created by the bootstrap layer."
  type        = string
}

# ---------------------------------------------------------------------------
# IAM roles
# ---------------------------------------------------------------------------
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

variable "extra_plan_actions" {
  description = "Additional read-only IAM actions for the plan role as the POC adds resource types."
  type        = list(string)
  default     = []
}

variable "extra_deploy_actions" {
  description = "Additional write IAM actions for the deploy role as the POC adds resource types."
  type        = list(string)
  default     = []
}

# SECURITY: enabling this lets the deploy role write IAM, which is inherently
# privilege-adjacent. It is scoped to <project_name>-* resources and paired
# with an explicit Deny protecting the plan and deploy roles themselves. Set
# false to run the backend layer only from a human workstation.
variable "enable_backend_self_management" {
  description = "Allow the CI roles to plan/apply the backend layer itself (IAM roles, policies, OIDC provider, state bucket config)."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------
variable "enable_bedrock_access" {
  description = "Grant the plan role permission to invoke the Bedrock inference profile used by the AI layer."
  type        = bool
  default     = true
}

variable "bedrock_model_id" {
  description = "Inference profile ID the application passes to invoke_model, published to Actions as FINOPS_BEDROCK_MODEL."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "bedrock_inference_profile_arn" {
  description = "ARN of the Bedrock inference profile. From: aws bedrock get-inference-profile --inference-profile-identifier <id>"
  type        = string
  default     = null
}

variable "bedrock_foundation_model_arns" {
  description = "Foundation model ARNs for every region the inference profile routes to. AWS requires these alongside the profile ARN."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Additional tags merged onto every resource."
  type        = map(string)
  default     = {}
}
