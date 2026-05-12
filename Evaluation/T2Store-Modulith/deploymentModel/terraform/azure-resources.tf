# Azure Provider source and version being used
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "=2.92.0"
    }
     kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.0.0"
    }
  }
}

# Configure the Microsoft Azure Provider
provider "azurerm" {
  features {}
}

# Create a resource group
resource "azurerm_resource_group" "t2store" {
  name     = var.resource_group_name
  location = var.region
}

# Create Kubernetes Cluster
resource "azurerm_kubernetes_cluster" "t2store" {
  name                = "t2store-aks1"
  location            = var.region
  resource_group_name = azurerm_resource_group.t2store.name
  dns_prefix          = "t2storeaks1"

  default_node_pool {
    name       = "default_node"
    node_count = 1
    vm_size    = "standard_b4ms"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = {
    Environment = "Production"
  }
}
