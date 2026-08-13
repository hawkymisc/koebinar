#!/usr/bin/env bash
set -eu

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 rsync
systemctl enable --now docker

install -d -o ubuntu -g ubuntu -m 0750 /opt/koebinar
usermod -aG docker ubuntu
