resource "kubernetes_deployment" "gits_frontend" {
  metadata {
    name = "gits-frontend"
    labels = {
      app = "gits-frontend"
    }
    namespace = kubernetes_namespace.gits.metadata[0].name

    annotations = {
      "keel.sh/policy"    = "force"
      "keel.sh/match-tag" = "true"
      "keel.sh/trigger"   = "poll"
    }
  }

  spec {
    replicas = 1

    selector {
      match_labels = {
        app = "gits-frontend"
      }
    }

    template {
      metadata {
        labels = {
          app = "gits-frontend"
        }
      }

      spec {
        image_pull_secrets {
          name = kubernetes_secret.image_pull.metadata[0].name
        }

        container {
          image             = "ghcr.io/it-rex-platform/frontend:latest"
          image_pull_policy = "Always"

          name = "gits-frontend"

          resources {
            limits = {
              cpu    = "0.5"
              memory = "512Mi"
            }
            requests = {
              cpu    = "50m"
              memory = "50Mi"
            }
          }

          env {
            name  = "NEXT_PUBLIC_BACKEND_URL"
            value = "/api"
          }
          env {
            name  = "NEXT_PUBLIC_OAUTH_REDIRECT_URL"
            value = "http://orange.informatik.uni-stuttgart.de"
          }
          env {
            name  = "NEXT_PUBLIC_OAUTH_CLIENT_ID"
            value = "gits-frontend"
          }
          env {
            name  = "NEXT_PUBLIC_OAUTH_AUTHORITY"
            value = "http://orange.informatik.uni-stuttgart.de/keycloak/realms/GITS"
          }

          liveness_probe {
            http_get {
              path = "/"
              port = 3000

            }

            initial_delay_seconds = 9
            period_seconds        = 9
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "gits_frontend" {
  metadata {
    name      = "gits-frontend"
    namespace = kubernetes_namespace.gits.metadata[0].name
  }
  spec {
    selector = {
      app = kubernetes_deployment.gits_frontend.metadata[0].labels.app
    }

    port {
      port        = 80
      target_port = 3000
    }

    type = "NodePort"
  }
}

