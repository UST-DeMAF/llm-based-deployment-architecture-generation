variable "image_pull_secret" {
  sensitive = true
  type      = string
}
variable "keycloak_admin_pw" {
  sensitive = true
  type      = string
}
