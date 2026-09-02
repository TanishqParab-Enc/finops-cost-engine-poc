output "provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider, whether created here or reused."
  value       = local.provider_arn
}

output "provider_url" {
  description = "Issuer URL of the GitHub Actions OIDC provider."
  value       = "https://token.actions.githubusercontent.com"
}

output "was_created" {
  description = "True when this module created the provider rather than reusing one."
  value       = local.create
}
