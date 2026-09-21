# Authentication comes from the workflow's OIDC exchange (ARM_USE_OIDC=1 plus
# ARM_CLIENT_ID / ARM_TENANT_ID / ARM_SUBSCRIPTION_ID). No client secret and no
# credentials are ever set here.
provider "azurerm" {
  features {}

  subscription_id = var.subscription_id
}
