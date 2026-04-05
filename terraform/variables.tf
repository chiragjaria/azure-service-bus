variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "servicebus_namespace_name" {
  description = "Service Bus namespace name"
  type        = string
}

variable "queue_name" {
  description = "Queue name for orders"
  type        = string
}

variable "key_vault_name" {
  description = "Key Vault name"
  type        = string
}

variable "function_app_name" {
  description = "Function App name"
  type        = string
}

variable "storage_account_name" {
  description = "Storage account name"
  type        = string
}

variable "resource_group_name_storage" {
  description = "Storage account name"
  type        = string
}
