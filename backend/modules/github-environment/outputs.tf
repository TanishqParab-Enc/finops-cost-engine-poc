output "environment_name" {
  description = "Name of the managed GitHub Actions environment."
  value       = github_repository_environment.this.environment
}

output "reviewers_configured" {
  description = "True when required reviewers are enforced on this environment."
  value       = local.manage_reviewers
}

output "environment_variable_names" {
  description = "Names of the environment-level variables managed here."
  value       = sort(keys(var.environment_variables))
}

output "repository_variable_names" {
  description = "Names of the repository-level variables managed here."
  value       = sort(keys(var.repository_variables))
}
