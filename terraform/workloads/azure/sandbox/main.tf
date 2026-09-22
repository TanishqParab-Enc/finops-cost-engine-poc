# Azure sandbox: the smallest workload that still exercises the full governed
# lifecycle (init -> validate -> plan -> Infracost -> policy -> approval ->
# saved-plan apply -> destroy) against real, genuinely priced Azure resources.
#
# Deliberately small. The point is to prove the reusable FinOps pipeline on a
# second cloud, not to mirror the AWS ecommerce-platform resource-for-resource.
#
# Comment-only marker so this path appears in the pull request diff and the
# registry's brownfield routing selects azure-sandbox. No resource, variable,
# provider, backend, state key, name, tag or dependency is affected.

locals {
  name_prefix = "${var.application_name}-${var.environment}"

  # Azure tags are the equivalent of the AWS workloads' default_tags.
  tags = merge(
    {
      Project     = "finops-poc"
      Environment = var.environment
      Workload    = var.application_name
      ManagedBy   = "Terraform"
    },
    var.tags,
  )
}

# Pre-existing and shared with unrelated workloads: read, never created,
# never destroyed. Every resource below is namespaced by local.name_prefix so
# the sandbox can only ever own what it created.
data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

resource "azurerm_virtual_network" "main" {
  name                = "${local.name_prefix}-vnet"
  address_space       = [var.vnet_address_space]
  location            = var.location
  resource_group_name = data.azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_subnet" "app" {
  name                 = "${local.name_prefix}-subnet-app"
  resource_group_name  = data.azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.app_subnet_prefix]
}

# No inbound rule is defined: the VM is reachable only from inside the VNet.
# The sandbox never needs public ingress, so none is created.
resource "azurerm_network_security_group" "app" {
  name                = "${local.name_prefix}-nsg-app"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.main.name
  tags                = local.tags

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "app" {
  subnet_id                 = azurerm_subnet.app.id
  network_security_group_id = azurerm_network_security_group.app.id
}

resource "azurerm_network_interface" "app" {
  name                = "${local.name_prefix}-nic"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.main.name
  tags                = local.tags

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.app.id
    private_ip_address_allocation = "Dynamic"
  }
}

# A cost-driving resource Infracost prices from the plan: vm_size is the
# primary cost lever this sandbox uses for brownfield incremental-cost tests.
resource "azurerm_linux_virtual_machine" "app" {
  name                = "${local.name_prefix}-vm"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = var.location
  size                = var.vm_size
  admin_username      = var.admin_username
  tags                = local.tags

  network_interface_ids = [azurerm_network_interface.app.id]

  # Key-based only; password authentication is disabled by default in the
  # provider for Linux VMs and is left that way deliberately.
  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = var.os_disk_type
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }
}

# Second cost lever: an explicitly sized managed data disk.
resource "azurerm_managed_disk" "data" {
  name                 = "${local.name_prefix}-data-disk"
  resource_group_name  = data.azurerm_resource_group.main.name
  location             = var.location
  storage_account_type = var.data_disk_type
  disk_size_gb         = var.data_disk_size_gb
  create_option        = "Empty"
  tags                 = local.tags
}

resource "azurerm_virtual_machine_data_disk_attachment" "data" {
  managed_disk_id    = azurerm_managed_disk.data.id
  virtual_machine_id = azurerm_linux_virtual_machine.app.id
  lun                = 0
  caching            = "ReadWrite"
}

# Consumption-priced: contributes only via infracost-usage.yml assumptions.
resource "azurerm_storage_account" "assets" {
  name                            = replace("${local.name_prefix}assets", "-", "")
  resource_group_name             = data.azurerm_resource_group.main.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = var.storage_replication_type
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  tags                            = local.tags
}
