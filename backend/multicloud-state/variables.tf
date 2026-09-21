variable "project_name" {
  description = "Project prefix; must match the existing AWS backend so state prefixes line up."
  type        = string
  default     = "finops-poc"
}

variable "aws_region" {
  description = "Region of the existing Terraform state bucket."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "The EXISTING shared Terraform state bucket. Not created here."
  type        = string
}

variable "github_owner" {
  description = "GitHub organisation or user that owns the repository."
  type        = string
}

variable "github_repository" {
  description = "Repository name trusted to assume this role."
  type        = string
}

variable "github_owner_id" {
  description = "Numeric owner ID, for GitHub's immutable OIDC subject form."
  type        = string
  default     = null
}

variable "github_repository_id" {
  description = "Numeric repository ID, for GitHub's immutable OIDC subject form."
  type        = string
  default     = null
}

variable "allowed_branches" {
  description = "Branches whose pushes may assume this role for state access."
  type        = list(string)
  default     = ["main"]
}

variable "github_environments" {
  description = "GitHub Environments whose deploy/destroy jobs may assume this role."
  type        = list(string)
  default     = ["dev"]
}

variable "environments" {
  description = "Environment segments this role may reach in the state key prefix."
  type        = list(string)
  default     = ["dev"]
}

# Deliberately excludes "aws": the AWS workloads keep their own roles, so this
# role can never reach validated AWS workload state.
variable "managed_clouds" {
  description = "Cloud segments this role may reach in the state key prefix."
  type        = list(string)
  default     = ["azure", "gcp"]

  validation {
    condition     = !contains(var.managed_clouds, "aws")
    error_message = "managed_clouds must not include 'aws'; AWS workload state stays with the existing AWS roles."
  }
}
