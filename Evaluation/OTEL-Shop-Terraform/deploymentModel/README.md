# TERRAFORM

## Linux / MacOS

To execute the terraform build run:

```shell
terraform init 
terraform apply
```

## Windows

To execute the build first change the docker provider from the Linux version to the Windows version both are given in the main.tf file and have to comment in / out for Windows it should look like this:

```shell
provider "docker" {
  # Use on linux or mac
  # host = "unix:///var/run/docker.sock"
  # Use on windows
  host = "npipe:////.//pipe//docker_engine"
}
```

Also, you have to set the ```project_path``` variable to the main directory of the open-telemetry-demo.

If the open telemetry demo is in your user documents folder your path variable should look like this.

```shell
variable "project_path" {
  type = string
  default = "c:\\Users\\YourUser\\Documents\\open-telemetry-demo"
  description = "Path to the project"
}
```

The last step is to change the ```host_path``` attributes fo the of the ```flagd``` ```grafana```  ```otelcol``` and ```prometheus``` from the Linux path using the abspath function to the Windows version without this function. Both are supplied in the main.tf and have to be commented in or out. They should look like this.

```shell
#volumes {
    # linux or mac
    #host_path      = abspath("../src/grafana/grafana.ini")
    # windows
    host_path      = "${var.project_path}${var.seperator}src${var.seperator}grafana${var.seperator}grafana.ini"
    container_path = "/etc/grafana/grafana.ini"
 }
 ```

 After that changes, you can run

 ```shell
terraform init 
terraform apply
```

to start the application.

Note: This is currently necessary because the abspath function currently produces paths that are not working with the Terraform provider on Windows because it uses the wrong separator. ```/``` instead of ```\```.
