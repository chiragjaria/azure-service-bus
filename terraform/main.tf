terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

# ── Reference Existing Resources ──────────────────────────────
data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

data "azurerm_storage_account" "sa" {
  name                = var.storage_account_name
  resource_group_name = data.azurerm_resource_group.rg2.name
}

data "azurerm_key_vault" "kv" {
  name                = var.key_vault_name
  resource_group_name = data.azurerm_resource_group.rg.name
}

# ═══════════════════════════════════════════════════════════════
# SERVICE BUS NAMESPACE (container for queues & topics)
# ═══════════════════════════════════════════════════════════════
resource "azurerm_servicebus_namespace" "sb" {
  name                = var.servicebus_namespace_name
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  sku                 = "Standard"   # Standard = queues + topics support
}

# ═══════════════════════════════════════════════════════════════
# SERVICE BUS QUEUE (one sender → one receiver)
# ═══════════════════════════════════════════════════════════════
resource "azurerm_servicebus_queue" "orders" {
  name         = var.queue_name
  namespace_id = azurerm_servicebus_namespace.sb.id

  # Message handling rules
  max_delivery_count                         = 10        # retry 10 times
  lock_duration                              = "PT1M"    # lock for 1 min while processing
  default_message_ttl                        = "P14D"    # message lives 14 days
  enable_dead_lettering_on_message_expiration = true     # failed → dead-letter queue
}

# ═══════════════════════════════════════════════════════════════
# STORE CONNECTION STRING IN AKV (for secure access)
# ═══════════════════════════════════════════════════════════════
resource "azurerm_key_vault_secret" "sb_connection" {
  name         = "sb-connection-string"
  value        = azurerm_servicebus_namespace.sb.default_primary_connection_string
  key_vault_id = data.azurerm_key_vault.kv.id
}

# ═══════════════════════════════════════════════════════════════
# APP SERVICE PLAN (runs the Function App)
# ═══════════════════════════════════════════════════════════════
resource "azurerm_service_plan" "plan" {
  name                = "asp-sb-dev-cj"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "Y1"  # Consumption tier (pay per execution)
}

# ═══════════════════════════════════════════════════════════════
# APPLICATION INSIGHTS (monitoring & logs)
# ═══════════════════════════════════════════════════════════════
resource "azurerm_application_insights" "ai" {
  name                = "appi-sb-dev-cj"
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  application_type    = "web"
}

# ═══════════════════════════════════════════════════════════════
# FUNCTION APP (handles orders + Service Bus integration)
# ═══════════════════════════════════════════════════════════════
resource "azurerm_linux_function_app" "func" {
  name                       = var.function_app_name
  resource_group_name        = data.azurerm_resource_group.rg.name
  location                   = data.azurerm_resource_group.rg.location
  storage_account_name       = data.azurerm_storage_account.sa.name
  storage_account_access_key = data.azurerm_storage_account.sa.primary_access_key
  service_plan_id            = azurerm_service_plan.plan.id

  # System-assigned managed identity (for AKV access)
  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = "3.10"
    }
  }

  # ── Environment variables ────────────────────────────────────
  app_settings = {
    FUNCTIONS_WORKER_RUNTIME       = "python"
    APPINSIGHTS_INSTRUMENTATIONKEY = azurerm_application_insights.ai.instrumentation_key
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"

    # Service Bus credentials from AKV
    SB_CONNECTION_STRING = "@Microsoft.KeyVault(VaultName=${var.key_vault_name};SecretName=sb-connection-string)"
    SB_QUEUE_NAME        = var.queue_name

    # Database credentials from AKV (from Topic 1)
    DB_HOST = "@Microsoft.KeyVault(VaultName=${var.key_vault_name};SecretName=phost)"
    DB_NAME = "@Microsoft.KeyVault(VaultName=${var.key_vault_name};SecretName=pdb)"
    DB_USER = "@Microsoft.KeyVault(VaultName=${var.key_vault_name};SecretName=puser)"
    DB_PASS = "@Microsoft.KeyVault(VaultName=${var.key_vault_name};SecretName=ppassword)"
  }
}

# ═══════════════════════════════════════════════════════════════
# AKV ACCESS POLICY (allow Function App to read secrets)
# ═══════════════════════════════════════════════════════════════
resource "azurerm_key_vault_access_policy" "func_policy" {
  key_vault_id = data.azurerm_key_vault.kv.id
  tenant_id    = azurerm_linux_function_app.func.identity[0].tenant_id
  object_id    = azurerm_linux_function_app.func.identity[0].principal_id

  secret_permissions = ["Get", "List"]
}
