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
helm install mongo --set auth.enabled=false bitnami/mongodb

kubectl create -f k8/.