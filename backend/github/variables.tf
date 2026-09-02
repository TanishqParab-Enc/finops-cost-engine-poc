variable "github_owner" {
  description = "GitHub organization or user that owns the repository."
  type        = string
}

variable "github_repository" {
  description = "Repository name, without the owner prefix."
  type        = string
}

variable "primary_environment" {
  description = "Environment key that owns the repository-level variables, so they are only written once."
  type        = string
  default     = "production"
}

variable "repository_variables" {
  description = "Non-secret repository-level Actions variables. Never put tokens here - they land in Terraform state."
  type        = map(string)
  default     = {}
}

variable "environments" {
  description = "GitHub Actions environments to manage, keyed by environment name."

  type = map(object({
    reviewer_user_ids            = optional(list(number), [])
    reviewer_team_ids            = optional(list(number), [])
    prevent_self_review          = optional(bool, true)
    wait_timer_minutes           = optional(number, 0)
    restrict_deployment_branches = optional(bool, true)
    only_protected_branches      = optional(bool, false)
    deployment_branch_patterns   = optional(list(string), ["main"])
    variables                    = optional(map(string), {})
  }))

  default = {}
}
