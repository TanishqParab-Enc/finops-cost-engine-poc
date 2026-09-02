variable "github_repository" {
  description = "Repository name, without the owner prefix. The owner comes from the github provider configuration."
  type        = string
}

variable "environment_name" {
  description = "Name of the GitHub Actions environment, e.g. production."
  type        = string
}

variable "reviewer_user_ids" {
  description = "Numeric GitHub user IDs required to approve deployments. Get one with: gh api /users/<login> --jq .id"
  type        = list(number)
  default     = []

  validation {
    condition     = length(var.reviewer_user_ids) <= 6
    error_message = "GitHub allows at most 6 required reviewers."
  }
}

variable "reviewer_team_ids" {
  description = "Numeric GitHub team IDs required to approve deployments. Organization repositories only."
  type        = list(number)
  default     = []
}

variable "prevent_self_review" {
  description = "Block the user who triggered the run from approving their own deployment."
  type        = bool
  default     = true
}

variable "wait_timer_minutes" {
  description = "Minutes to delay before a deployment proceeds. 0 disables the timer."
  type        = number
  default     = 0

  validation {
    condition     = var.wait_timer_minutes >= 0 && var.wait_timer_minutes <= 43200
    error_message = "wait_timer_minutes must be between 0 and 43200."
  }
}

variable "restrict_deployment_branches" {
  description = "Restrict which branches may deploy to this environment."
  type        = bool
  default     = true
}

variable "only_protected_branches" {
  description = "When restricting branches, allow only protected branches instead of custom patterns."
  type        = bool
  default     = false
}

variable "deployment_branch_patterns" {
  description = "Branch name patterns allowed to deploy, used when only_protected_branches is false."
  type        = list(string)
  default     = ["main"]
}

variable "environment_variables" {
  description = "Non-secret environment-level Actions variables. Never put tokens here."
  type        = map(string)
  default     = {}
}

variable "repository_variables" {
  description = "Non-secret repository-level Actions variables. Never put tokens here."
  type        = map(string)
  default     = {}
}
