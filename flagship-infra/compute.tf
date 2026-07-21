resource "digitalocean_droplet" "k3s_master" {
  name     = "k3s-master"
  region   = "blr1"
  size     = "s-2vcpu-4gb"
  image    = "ubuntu-24-04-x64"
  vpc_uuid = digitalocean_vpc.flagship_vpc.id
  ssh_keys = [57553799]
  
  user_data = <<-EOF
              #!/bin/bash
              curl -sfL https://get.k3s.io | sh -
              EOF

  tags = ["k3s", "master"]
}

resource "digitalocean_droplet" "k3s_worker_standard" {
  name     = "k3s-worker-standard"
  region   = "blr1"
  size     = "s-2vcpu-4gb"
  image    = "ubuntu-24-04-x64"
  vpc_uuid = digitalocean_vpc.flagship_vpc.id
  ssh_keys = [57553799]
  
  tags = ["k3s", "worker"]
}

resource "digitalocean_droplet" "k3s_worker_mlops" {
  name     = "k3s-worker-mlops"
  region   = "blr1"
  size     = "s-4vcpu-8gb"
  image    = "ubuntu-24-04-x64"
  vpc_uuid = digitalocean_vpc.flagship_vpc.id
  ssh_keys = [57553799]
  
  tags = ["k3s", "worker", "mlops"]
}
