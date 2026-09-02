variable "project_name" {
  description = "Project identifier used to derive resource names."
  type        = string
  default     = "finops-poc"
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "aws_region" {
  description = "AWS region for this environment."
  type        = string
  default     = "us-east-1"
}

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
  description = "GitHub Actions environment gating deployments. Scopes the deploy role's OIDC trust subject."
  type        = string
  default     = "production"
}

variable "allowed_branches" {
  description = "Branches whose pushes may assume the plan role."
  type        = list(string)
  default     = ["main"]
}

variable "create_oidc_provider" {
  description = "Create the account-wide GitHub OIDC provider from this environment."
  type        = bool
  default     = false
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing GitHub OIDC provider to reuse."
  type        = string
  default     = null
}

variable "state_bucket_name" {
  description = "Shared Terraform state bucket created by the bootstrap layer."
  type        = string
}

variable "enable_bedrock_access" {
  description = "Grant the plan role Bedrock invoke permission for the AI layer."
  type        = bool
  default     = true
}

variable "bedrock_model_id" {
  description = "Inference profile ID passed to invoke_model."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "bedrock_inference_profile_arn" {
  description = "ARN of the Bedrock inference profile."
  type        = string
  default     = null
}

variable "bedrock_foundation_model_arns" {
  description = "Foundation model ARNs for every region the profile routes to."
  type        = list(string)
  default     = []
}

variable "extra_plan_actions" {
  description = "Additional read-only IAM actions for the plan role."
  type        = list(string)
  default     = []
}

variable "extra_deploy_actions" {
  description = "Additional write IAM actions for the deploy role."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Additional tags merged onto every resource."
  type        = map(string)
  default     = {}
}
