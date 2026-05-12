# BoutiqueShop

This directory contains the deployment artifacts of the
Google Cloud Online Boutique microservices application
used as an out-of-distribution evaluation scenario.

## Source Application
Google Cloud Online Boutique

Repository:
https://github.com/GoogleCloudPlatform/microservices-demo

## Deployment Technologies
- Kubernetes
- Terraform
- Google Cloud Platform (GCP)

## Directory Contents
- deploymentModel/: Original deployment artifacts
- expected.yaml: Manually curated EDMM reference model
- actual.yaml: Example generated EDMM model

## Evaluation Purpose
This scenario evaluates the generalization capability of
the proposed transformation pipelines on previously unseen
deployment artifacts.

## Notes
Unlike the other evaluation scenarios, this deployment
case was not used during knowledge base construction or
pipeline development and therefore represents an
out-of-distribution evaluation case.