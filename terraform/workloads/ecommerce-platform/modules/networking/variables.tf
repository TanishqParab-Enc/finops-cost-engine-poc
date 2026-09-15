variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
}

variable "availability_zones" {
  description = "AZs to spread subnets across."
  type        = list(string)
}

variable "az_count" {
  description = "Number of AZs actually used, already reconciled against the CIDR lists."
  type        = number
}

variable "public_subnet_cidrs" {
  description = "One public subnet per AZ."
  type        = list(string)
}

variable "app_subnet_cidrs" {
  description = "One private application subnet per AZ."
  type        = list(string)
}

variable "data_subnet_cidrs" {
  description = "One private data subnet per AZ."
  type        = list(string)
}

variable "nat_gateway_count" {
  description = "NAT gateways to create."
  type        = number
}
