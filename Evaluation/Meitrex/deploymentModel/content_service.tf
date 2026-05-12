resource "kubernetes_deployment" "gits_content_service" {
  depends_on = [helm_release.content_service_db, helm_release.dapr, helm_release.keel, kubernetes_secret.image_pull]
  metadata {

    name = "gits-content-service"
    labels = {
      app = "gits-content-service"
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
        app = "gits-content-service"
      }
    }

    template {
      metadata {
        labels = {
          app = "gits-content-service"
        }
        annotations = {
          "dapr.io/enabled"   = true
          "dapr.io/app-id"    = "content-service"
          "dapr.io/app-port"  = 4001
          "dapr.io/http-port" = 4000
        }
      }

      spec {

        image_pull_secrets {
          name = kubernetes_secret.image_pull.metadata[0].name
        }


        container {
          image             = "ghcr.io/it-rex-platform/content_service:latest"
          image_pull_policy = "Always"

          name = "gits-content-service"

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
            name  = "SPRING_DATASOURCE_URL"
            value = "jdbc:postgresql://content-service-db-postgresql:5432/content-service"
          }

          env {
            name  = "SPRING_DATASOURCE_USERNAME"
            value = "gits"
          }

          env {
            name  = "SPRING_DATASOURCE_PASSWORD"
            value = random_password.content_service_db_pass.result
          }

           liveness_probe {
             http_get {
               path = "/actuator/health/liveness"
               port = 4001

             }

             initial_delay_seconds = 30
             period_seconds        = 9
           }

           readiness_probe {
             http_get {
               path = "/actuator/health/readiness"
               port = 4001

             }

             initial_delay_seconds = 30
             period_seconds        = 9
           }
        }
      }
    }
  }
}

resource "random_password" "content_service_db_pass" {
  length  = 32
  special = false
}

resource "helm_release" "content_service_db" {
  name       = "content-service-db"
  repository = "oci://registry-1.docker.io/bitnamicharts"
  chart      = "postgresql"
  namespace  = kubernetes_namespace.gits.metadata[0].name

  set {
    name  = "global.postgresql.auth.database"
    value = "content-service"
  }

  set {
    name  = "postgres.auth.enablePostgresUser"
    value = "false"
  }

  set {
    name  = "global.postgresql.auth.username"
    value = "gits"
  }

  set {
    name  = "global.postgresql.auth.password"
    value = random_password.content_service_db_pass.result
  }
}
