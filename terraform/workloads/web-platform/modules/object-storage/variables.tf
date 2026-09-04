variable "name_prefix" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "versioning_enabled" {
  type = bool
}

variable "noncurrent_version_expiration_days" {
  type = number
}
