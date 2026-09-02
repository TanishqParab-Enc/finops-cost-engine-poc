# GitHub Actions OIDC identity provider.
#
# Only one OIDC provider per issuer URL may exist per AWS account, so this
# module supports both creating it and reusing an existing one. Verified
# 2026-09-02: account 024125831628 had no OIDC providers, so create_provider
# defaults to true.

locals {
  create = var.create_provider && var.existing_provider_arn == null

  provider_arn = local.create ? aws_iam_openid_connect_provider.github[0].arn : var.existing_provider_arn
}

resource "aws_iam_openid_connect_provider" "github" {
  count = local.create ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = var.thumbprint_list

  tags = merge(
    {
      Project   = var.project_name
      ManagedBy = "Terraform"
      Purpose   = "GitHub Actions OIDC federation"
    },
    var.tags,
  )
}
