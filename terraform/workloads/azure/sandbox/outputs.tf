output "resource_group_name" {
  value = data.azurerm_resource_group.main.name
}

output "location" {
  value = var.location
}

output "vm_name" {
  value = azurerm_linux_virtual_machine.app.name
}

output "storage_account_name" {
  value = azurerm_storage_account.assets.name
}

# The resource group is shared and must SURVIVE destroy, so verification keys
# off the sandbox's name prefix instead of the group's absence.
output "verification_scope" {
  description = "Identifies exactly the resources post-destroy verification expects to be gone."
  value = {
    resource_group = data.azurerm_resource_group.main.name
    subscription   = var.subscription_id
    name_prefix    = local.name_prefix
    storage_prefix = replace(local.name_prefix, "-", "")
  }
}

output "cost_levers" {
  description = "The parameters a brownfield change is expected to move."
  value = {
    vm_size           = var.vm_size
    data_disk_size_gb = var.data_disk_size_gb
    data_disk_type    = var.data_disk_type
    os_disk_type      = var.os_disk_type
  }
}
