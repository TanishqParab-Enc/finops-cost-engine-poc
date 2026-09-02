output "managed_environments" {
  description = "GitHub Actions environments managed by this layer."
  value       = sort(keys(module.environments))
}

output "environments_with_required_reviewers" {
  description = "Environments that enforce manual approval before deployment."
  value       = sort([for name, env in module.environments : name if env.reviewers_configured])
}

output "repository_variable_names" {
  description = "Names of repository-level Actions variables under management."
  value       = sort(keys(var.repository_variables))
}
