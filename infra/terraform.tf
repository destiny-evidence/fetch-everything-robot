terraform {
  required_version = ">= 1.0"

  cloud {
    organization = "destiny-evidence"
    workspaces {
      project = "DESTINY"
      tags = ["fetch-everything-robot"]
    }
  }

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.81.0"
    }
  }
}

provider "azurerm" {
  features {}
}
