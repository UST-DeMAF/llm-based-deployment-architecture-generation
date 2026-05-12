---

# GITS Infrastructure

## Overview

This repository contains the Terraform scripts responsible for orchestrating the deployment of the GITS Platform on a Kubernetes cluster.

## Deployment Approach

### Terraform and State Management

We employ Terraform as the central tool for infrastructure-as-code, managing every facet of our Kubernetes resources. At the moment, remote state management is not yet configured, mostly due to the inability to use Terraform Cloud as it's not possible to connect to the Kubernetes cluster from outside the university network. This means that the Terraform state files need to be manually transferred to the individual managing the cluster. This is a point of consideration for future improvements.

### Resource Deployment

Our infrastructure consists of a mixture of "raw" Kubernetes resources and Helm-based deployments. All GITS-services are deployed using raw Kubernetes manifests while we use Helm for standard resources like PostgreSQL databases, Keycloak and Minio to simplify management.

### Continuous Integration with Keel

Keel serves as our CI tool, automating the update process for our Kubernetes resources. The pull-based approach to CI is particularly advantageous in our setup, as our code and Docker images are hosted externally on GitHub, while the Kubernetes cluster resides within the university network.

### Ingress Configuration

All services are exposed through an Nginx ingress that is presumed to already exist in the target cluster. This ingress handles routing and SSL termination, providing a unified access point to various services. Currently, self-signed certs are used due to the difficulty of using Let's Encrypt without a public endpoint. While this would be possible using DNS validation, this is complex to setup and requires a supported DNS provider.

### it-rex.ch

We own the domain `it-rex.ch`, which is currently only used for exposing the Minio service. This is a workaround to the cluster's limitation of having a single DNS entry, `orange.informatik.uni-stuttgart.de`. Minio requires its own subdomain, making this arrangement necessary. The domain is owned and managed by Valentin (GitHub: v-morlock). It could also be used to expose the whole system under a nicer domain and possibly enable obtaining trusted SSL certs.

## Repository Structure

### General Infrastructure Resources

- **main.tf**: Defines the Kubernetes namespace `gits` and establishes image pull secrets required for pulling Docker images from external repositories.
- **ingress.tf**: Sets up the Nginx ingress for managing external access. Configurations for SSL redirection and proxy buffer sizes are also defined here. All services to be exposed have to be configured here.
- **dapr.tf**: Deploys the Dapr runtime using Helm charts. Also includes the setup for state and pub-sub components using Redis.
- **keel.tf**: Manages the deployment of Keel, a tool used for automated Kubernetes deployments, via Helm charts.
- **keycloak.tf**: Handles the setup for Keycloak, used for identity and access management. It utilizes Helm charts for deployment and includes admin user and password settings.

### Frontend Deployment

In `frontend.tf`, the GITS frontend is deployed as a Kubernetes Deployment and exposed through a Kubernetes Service. The deployment specifies environment variables for OAuth and backend URL configurations and includes a liveness probe to monitor the health of the frontend service.

### Backend Services Deployment

The backend services are generally structured as follows:

- **Kubernetes Deployment**: Each service is deployed as a Kubernetes Deployment, complete with a Dapr sidecar for http and pub-sub communication.
- **Database**: A Helm-managed PostgreSQL database is associated with each service, configured with a random password and the default db.
- **Optional Resources**: Some services include additional resources like Horizontal Pod Autoscalers or Minio deployments for content storage.

While the individual backend deployments might look repetitive, keeping them separate allows us to adapt each service to its specifics and add additional resources like Minio or autoscalers where necessary.

### GraphQL Gateway Deployment

The GraphQL Gateway, configured in `gateway.tf`, serves as the central entry point for all backend services. It routes incoming HTTP requests to the respective backend services via Dapr. Like other backends, it's deployed as a Kubernetes Deployment and exposed via a Kubernetes Service. An autoscaler and liveness/readiness probes are also configured to ensure scalability and health monitoring.

### Prerequisites

- **Kubernetes Cluster**: A running cluster with admin access, a working Nginx ingress controller, the capability to deploy Persistent Volumes and Load Balancers. Place the cluster credentials in a `kubeconfig.yaml` file within the repository.
- **Terraform CLI**: Ensure you have version >= 1.0.11 installed.
- **University VPN**: If managing the existing cluster, a connection to the university's VPN is required.
- **Terraform State**: For managing the existing cluster, obtain and place the current Terraform state within the repository.
- **`variables.tf`**: Either create a new `variables.tf` file or obtain the existing one when managing the existing cluster. To generate a GitHub token for pulling images, log in to Docker and execute the following shell command to create a new `terraform.tfvars` file:
  ```sh
  echo "image_pull_secret = \"$(cat ~/.docker/config.json | tr -d '[:space:]' | sed -e s/\"/\\\\\"/g)\"" > terraform.tfvars
  ```

### Getting Started

1. **Clone the Repository**: Clone this Terraform repository to your local machine.
2. **Navigate to the Repo**: Open a terminal and navigate to the repository directory.
3. **Setup**: Ensure all prerequisites are met as outlined in the Prerequisites section.
4. **Initialize Terraform**: Run `terraform init` to initialize the Terraform workspace.
5. **Apply Configuration**: Execute `terraform apply` to deploy the resources to your Kubernetes cluster.

### Troubleshooting

- **Expired GitHub Token**: GitHub tokens used for pulling images expire occasionally. If you encounter issues related to image pulls, regenerate the token and update `terraform.tfvars`.
- **Disappearing Dapr Sidecars**: If Dapr sidecars disappear, causing communication to stop working in the cluster, try restarting the affected deployments.
- **Schema Changes in Services**: If there are schema changes in individual services without changes in the gateway code, a restart of the gateway deployment is required.

Hint: For easier management and debugging, it helps to use a Kubernetes management UI like Lens to connect to the cluster, restart deployments or setup port forwarding.
