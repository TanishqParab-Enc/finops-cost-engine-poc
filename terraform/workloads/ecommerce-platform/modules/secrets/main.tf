# Application secrets the storefront and workers read at boot. The database
# master password is NOT here - RDS manages that itself (see the database
# module), so it never passes through Terraform state.
resource "random_password" "session_signing_key" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name        = "${var.name_prefix}-app-config"
  description = "Storefront runtime configuration and signing key"

  # Short window so a POC teardown does not leave a name reserved for 30 days.
  recovery_window_in_days = 0

  tags = merge(var.tags, { Name = "${var.name_prefix}-app-config" })
}

# Generated, never hard-coded. Any real integration credential would be added
# out of band rather than committed here.
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id

  secret_string = jsonencode({
    session_signing_key = random_password.session_signing_key.result
    cache_endpoint      = var.cache_endpoint
    order_queue_url     = var.order_queue_url
    asset_bucket        = var.asset_bucket
  })
}
