variable "location" {
  type    = string
  default = "eastus"
}

variable "resource_group_name" {
  type    = string
  default = "finops-poc-rg"
}

variable "environment" {
  type    = string
  default = "Dev"
}

variable "service" {
  type    = string
  default = "finops-poc"
}

variable "vm_size" {
  type    = string
  default = "Standard_B1s"
}

variable "instance_count" {
  type    = number
  default = 1
}

variable "os_disk_type" {
  type    = string
  default = "StandardSSD_LRS"
}

variable "os_disk_size_gb" {
  type    = number
  default = 32
}

variable "data_disk_count" {
  type    = number
  default = 0
}

variable "data_disk_size_gb" {
  type    = number
  default = 512
}

variable "data_disk_type" {
  type    = string
  default = "Premium_LRS"
}

variable "enable_public_ip" {
  type    = bool
  default = false
}
