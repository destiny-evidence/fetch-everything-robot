variable "app_name" {
  description = "Name of the app being deployed."
  default = "fetch-everything-robot"
  type = string
}

variable "robot_id" {
  description = "The id the robot will send to destiny repository to identify itself."
}

variable "robot_secret" {
  description = "The secret the robot will use in HMAC auth with destiny repository."
  sensitive   = true
}

variable "elsevier_scopus_key" {
  description = "The Elsevier Scopus API key the robot will use to authenticate with the Scopus API."
  sensitive   = true
}

variable "elsevier_scopus_inst_token" {
  description = "The Elsevier Scopus institutional token the robot will use to authenticate with the Scopus API."
  sensitive   = true
}

variable "destiny_repository_url" {
  description = "Url to configure the robot to post callbacks to."
}

# Variables below this line are for deploying the fetch everything robot.
# These may not be necessary for your use case
variable "container_registry_name" {
  description = "Name of the container registry where fetch everything robot images are pushed."

}

variable "container_registry_resource_group_name" {
  description = "Name of the container registry resource group."
}

variable "environment" {
  description = "Environment for the Fetch Everything Robot, should be either development, staging or production."
  default     = "development"
}

variable "owner_name" {
  description = "Name of the owner of the robot."
}

variable "owner_email" {
  description = "Email of the owner of the robot."
}

variable "environment_description" {
  description = "Description of the environment the robot is deployed to."
  default     = "warm"
}

variable "region_friendly_name" {
  description = "Friendly name of the region the robot is deployed to."
  default     = "Sweden Central"
}

variable "poll_interval_seconds" {
  description = "Interval in seconds between polling the destiny repository for new enhancement requests."
  default     = "3600"
}

variable "batch_size" {
  description = "Number of enhancement requests to fetch in each batch."
  default     = "10"
}
