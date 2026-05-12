

resource "kubernetes_ingress_v1" "gits" {
  metadata {
    name      = "gits"
    namespace = kubernetes_namespace.gits.metadata[0].name
    annotations = {
      "kubernetes.io/ingress.class"                   = "nginx"
      "nginx.ingress.kubernetes.io/ssl-redirect"      = "true"
      "nginx.ingress.kubernetes.io/proxy-body-size"   = "10m"
      "nginx.ingress.kubernetes.io/proxy-buffer-size" = "10m"
    }

  }

  spec {
    default_backend {
      service {
        name = "gits-frontend"
        port {
          number = 80
        }
      }
    }

    rule {
      http {
        path {
          backend {
            service {
              name = "gits-frontend"
              port {
                number = 3000
              }
            }
          }

          path = "/"
        }
      }
    }

    rule {
      http {
        path {
          backend {
            service {
              name = "gits-graphql-gateway"
              port {
                number = 80
              }
            }
          }

          path = "/graphql"
        }
      }
    }

    rule {
      http {
        path {
          backend {
            service {
              name = "keycloak"
              port {
                number = 80
              }
            }
          }

          path = "/keycloak"
        }
      }
    }

    rule {
      host = "minio.it-rex.ch"

      http {


        path {
          backend {
            service {
              name = "minio"
              port {
                number = 9000
              }
            }
          }

          path = "/"
        }
      }
    }
    rule {
      host = "minio-dashboard.it-rex.ch"

      http {
        path {
          backend {
            service {
              name = "minio"
              port {
                number = 9001
              }
            }
          }

          path = "/"
        }
      }
    }
  }
}

