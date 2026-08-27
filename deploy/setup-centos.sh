#!/usr/bin/env bash
# CentOS Stream 9 一次性环境准备脚本
# 用法：ssh root@<ECS-公网IP> 上去后跑 `bash setup-centos.sh`
set -euo pipefail

echo "==> 1/7 更新系统包索引"
dnf -y update

echo "==> 2/7 安装基础工具"
dnf -y install epel-release
dnf -y install git curl wget vim htop firewalld policycoreutils-python-utils

echo "==> 3/7 安装 Python 3.11"
dnf -y install python3.11 python3.11-pip python3.11-devel gcc

echo "==> 4/7 安装 Nginx + certbot"
dnf -y install nginx certbot python3-certbot-nginx

echo "==> 5/7 安装 PostgreSQL 客户端（用于 psql 连 RDS 调试）"
dnf -y install postgresql

echo "==> 6/7 创建应用用户和目录"
id -u sem >/dev/null 2>&1 || useradd -m -s /bin/bash sem
mkdir -p /opt/sem-backend
chown -R sem:sem /opt/sem-backend
mkdir -p /var/log/sem-backend
chown -R sem:sem /var/log/sem-backend

echo "==> 7/7 开启 firewalld + 放行 80/443"
systemctl enable --now firewalld
firewall-cmd --permanent --add-service=http
firewall-cmd --permanent --add-service=https
firewall-cmd --reload

echo
echo "==> 环境就绪。下一步："
echo "  1) scp 代码到 /opt/sem-backend"
echo "  2) sudo -u sem bash 进 sem 用户，建 venv 装依赖"
echo "  3) 安装 deploy/gsnipers.conf；该域名已有证书，不要覆盖现有证书"
echo "  4) systemctl enable --now sem-backend"
