output "servicebus_namespace" {
  description = "Service Bus namespace name"
  value       = azurerm_servicebus_namespace.sb.name
}

output "queue_name" {
  description = "Queue name"
  value       = azurerm_servicebus_queue.orders.name
}

output "function_app_url" {
  description = "Function App endpoint"
  value       = "https://${azurerm_linux_function_app.func.default_hostname}"
}

output "sb_connection_string" {
  description = "Service Bus connection string (sensitive)"
  value       = azurerm_servicebus_namespace.sb.default_primary_connection_string
  sensitive   = true
}
