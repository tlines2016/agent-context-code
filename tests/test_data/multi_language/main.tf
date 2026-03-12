# Terraform test file
resource "aws_instance" "web" {
  ami           = "ami-123456"
  instance_type = "t2.micro"

  tags = {
    Name = "web-server"
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

output "instance_ip" {
  value = aws_instance.web.public_ip
}

data "aws_ami" "latest" {
  most_recent = true
}

module "vpc" {
  source = "./modules/vpc"
}
