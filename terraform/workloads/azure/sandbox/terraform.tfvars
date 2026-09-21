# Committed baseline for the Azure sandbox. Editing this file changes cloud
# cost, which is exactly what the shared FinOps gate prices.
#
# subscription_id and admin_ssh_public_key are environment-specific and are NOT
# committed with real values - see terraform.tfvars.example. The workflow
# supplies them at plan time.

location         = "eastus"
environment      = "dev"
application_name = "azsandbox"

# Pre-existing, shared with unrelated workloads, and read as a data source.
# This configuration never creates or destroys it.
resource_group_name = "Azure-AI-Tagging-POC"

vnet_address_space = "10.60.0.0/16"
app_subnet_prefix  = "10.60.1.0/24"

# -- compute (primary cost lever) --
vm_size        = "Standard_B2s"
admin_username = "azureuser"
os_disk_type   = "StandardSSD_LRS"

# -- storage --
data_disk_type           = "StandardSSD_LRS"
data_disk_size_gb        = 32
storage_replication_type = "LRS"
