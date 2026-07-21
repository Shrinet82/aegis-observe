resource "digitalocean_vpc" "flagship_vpc" {
  name     = "flagship-vpc"
  region   = "blr1"
  ip_range = "10.10.10.0/24"
}

resource "digitalocean_firewall" "k3s_firewall" {
  name = "k3s-flagship-firewall"

  droplet_ids = [
    digitalocean_droplet.k3s_master.id,
    digitalocean_droplet.k3s_worker_standard.id,
    digitalocean_droplet.k3s_worker_mlops.id
  ]

  # Allow internal VPC traffic
  inbound_rule {
    protocol         = "tcp"
    port_range       = "1-65535"
    source_addresses = [digitalocean_vpc.flagship_vpc.ip_range]
  }
  
  inbound_rule {
    protocol         = "udp"
    port_range       = "1-65535"
    source_addresses = [digitalocean_vpc.flagship_vpc.ip_range]
  }

  inbound_rule {
    protocol         = "icmp"
    source_addresses = [digitalocean_vpc.flagship_vpc.ip_range]
  }

  # Allow essential ports from anywhere
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "6443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  # Allow all outbound traffic
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
