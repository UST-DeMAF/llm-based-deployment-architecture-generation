#!/bin/bash

# Azure login
az account show &>/dev/null || az login

# Setup Kubernetes Cluster
terraform -chdir=terraform/ init
terraform -chdir=terraform/ apply -auto-approve

# Set kubectl context
az aks get-credentials --resource-group t2store-resources --name t2store-aks1

# Install t2-store
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install mongo-cart --set auth.enabled=false bitnami/mongodb
helm install mongo-order --set auth.enabled=false bitnami/mongodb
helm install kafka bitnami/kafka --version 18.5.0 

kubectl create -f k8/.