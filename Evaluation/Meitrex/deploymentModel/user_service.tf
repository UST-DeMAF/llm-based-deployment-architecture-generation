resource "kubernetes_deployment" "gits_user_service" {
  depends_on = [helm_release.user_service_db, helm_release.dapr, helm_release.keel, kubernetes_secret.image_pull]
  metadata {
    name = "gits-user-service"
    labels = {
      app = "gits-user-service"
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
        app = "gits-user-service"
      }
    }

    template {
      metadata {
        labels = {
          app = "gits-user-service"
        }
        annotations = {
          "dapr.io/enabled"   = true
          "dapr.io/app-id"    = "user-service"
          "dapr.io/app-port"  = 5001
          "dapr.io/http-port" = 5000
          "dapr.io/sidecar-cpu-request" = "100m"
          "dapr.io/sidecar-cpu-limit"   = "200m"
          "dapr.io/sidecar-memory-request" = "100Mi"
          "dapr.io/sidecar-memory-limit"   = "200Mi"
          "dapr.io/env" = "GOMEMLIMIT=180MiB"
        }
      }

      spec {

        image_pull_secrets {
          name = kubernetes_secret.image_pull.metadata[0].name
        }


        container {
          image             = "ghcr.io/it-rex-platform/user_service:latest"
          image_pull_policy = "Always"

          name = "gits-user-service"

          resources {
            requests = {
              cpu    = "100m"
              memory = "500Mi"
            }
          }

          env {
            name  = "SPRING_DATASOURCE_URL"
            value = "jdbc:postgresql://user-service-db-postgresql:5432/user-service"
          }

          env {
            name  = "SPRING_DATASOURCE_USERNAME"
            value = "gits"
          }

          env {
            name  = "SPRING_DATASOURCE_PASSWORD"
            value = random_password.user_service_db_pass.result
          }

          env {
            name  = "KEYCLOAK_URL"
            value = "http://keycloak:80/keycloak"
          }
          env {
            name  = "KEYCLOAK_PASSWORD"
            value = var.keycloak_admin_pw
          }
           liveness_probe {
             http_get {
               path = "/actuator/health/liveness"
               port = 5001

             }

             initial_delay_seconds = 30
             period_seconds        = 9
           }

           readiness_probe {
             http_get {
               path = "/actuator/health/readiness"
               port = 5001

             }

             initial_delay_seconds = 30
             period_seconds        = 9
           }
        }
      }
    }
  }
}

resource "random_password" "user_service_db_pass" {
  length  = 32
  special = false
}

resource "helm_release" "user_service_db" {
  name       = "user-service-db"
  repository = "oci://registry-1.docker.io/bitnamicharts"
  chart      = "postgresql"
  namespace  = kubernetes_namespace.gits.metadata[0].name

  set {
    name  = "global.postgresql.auth.database"
    value = "user-service"
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
    value = random_password.user_service_db_pass.result
  }
}

resource "kubernetes_horizontal_pod_autoscaler_v2" "gits_user_service_hpa" {
  metadata {
    name = kubernetes_deployment.gits_user_service.metadata[0].name
    namespace = kubernetes_namespace.gits.metadata[0].name
  }

  spec {
    min_replicas = 1
    max_replicas = 10

    scale_target_ref {
      api_version = "apps/v1"
      kind = "Deployment"
      name = kubernetes_deployment.gits_user_service.metadata[0].name
    }

    metric {
      type = "Resource"
      resource {
        name = "cpu"
        target {
          type = "Utilization"
          average_utilization = 300
        }
      }
    }
  }  
}