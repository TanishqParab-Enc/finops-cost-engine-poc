terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }
}

# Mock credentials keep `terraform plan` offline for the POC. A real pipeline
# uses OIDC workload identity federation instead.
provider "azurerm" {
  features {}

  subscription_id            = "00000000-0000-0000-0000-000000000000"
  tenant_id                  = "00000000-0000-0000-0000-000000000000"
  client_id                  = "00000000-0000-0000-0000-000000000000"
  client_secret              = "mock-client-secret"
  skip_provider_registration = true
}

resource "azurerm_linux_virtual_machine" "app" {
  count = var.instance_count

  name                            = "finops-poc-vm-${count.index}"
  resource_group_name             = var.resource_group_name
  location                        = var.location
  size                            = var.vm_size
  admin_username                  = "azureuser"
  disable_password_authentication = true
  network_interface_ids           = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/${var.resource_group_name}/providers/Microsoft.Network/networkInterfaces/finops-poc-nic-${count.index}"]

  # Throwaway public key so `terraform plan` validates offline. Public keys are
  # not secrets and the matching private key was discarded.
  admin_ssh_key {
    username   = "azureuser"
    public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDH12kBRbXq6Eadi3xBr/R5mViQIsdROaxp6i0cyW5PdC9ao0xg7d/svlSZkVf0UBO96WQXMj5dXiyorw/cW+MN4JbLNgt27Aos8Qh1B//9m9FNANvsFHF6wMqOXJj/jIkmRA3NeaKQKrpkRNHSd6QTj0zg/mB/fYO/+eGiXaszExDpxiBI30JG6BYm1pPWJ4Oj5UmwCz8xxPNFOpM1rTjiBhtJ4pE6uhRHcne0fsSwqkW2mcJ7Af9XxHyKHwY2d1cOFLlCJfwMB/ES6/Db/N7gcAF0r/dKiLVtI45J+o0au/AgtBDzZ61G3gzs6Gq5Hq1NJHfzh8+Pz5//ubIq0q4P finops-poc-plan-only"
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = var.os_disk_type
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  tags = {
    Environment = var.environment
    Service     = var.service
  }
}

resource "azurerm_managed_disk" "data" {
  count = var.data_disk_count

  name                 = "finops-poc-data-${count.index}"
  resource_group_name  = var.resource_group_name
  location             = var.location
  storage_account_type = var.data_disk_type
  disk_size_gb         = var.data_disk_size_gb
  create_option        = "Empty"

  tags = {
    Environment = var.environment
    Service     = var.service
  }
}

resource "azurerm_public_ip" "egress" {
  count = var.enable_public_ip ? 1 : 0

  name                = "finops-poc-pip"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = {
    Environment = var.environment
    Service     = var.service
  }
}
