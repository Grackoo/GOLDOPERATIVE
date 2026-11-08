#!/bin/bash
# ==============================================================================
# AUREUS-SMC Script Automatizado de Despliegue en VPS Linux (Equinix NY4)
# Optimización de Kernel, TCP BBR, Chrony NTP y Servicio systemd
# ==============================================================================

set -e

echo "================================================================="
echo "   INICIANDO INSTALACION Y OPTIMIZACION DE AUREUS-SMC (NY4)     "
echo "================================================================="

# Verificar privilegios de root
if [ "$EUID" -ne 0 ]; then
  echo "[ERROR] Este script debe ejecutarse como root o con sudo."
  exit 1
fi

INSTALL_DIR="/opt/aureus-trading"
CURRENT_DIR=$(pwd)

echo "[1/6] Actualizando repositorios e instalando paquetes base..."
apt-get update -y
apt-get install -y build-essential curl git cpufrequtils chrony python3-pip python3-venv tzdata ethtool

echo "[2/6] Configurando zona horaria canónica de Nueva York (EST/EDT)..."
timedatectl set-timezone America/New_York

echo "[3/6] Aplicando optimizaciones de Kernel y red para latencia < 5ms..."
SYSCTL_CONF="/etc/sysctl.d/99-aureus-ny4.conf"
cat << 'EOF' > $SYSCTL_CONF
# Virtual Memory & SQLite WAL Direct I/O
vm.swappiness = 1
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10

# TCP Socket Buffers
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.core.optmem_max = 2048576
net.core.netdev_max_backlog = 50000

# Parámetros TCP de lectura y escritura
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_max_syn_backlog = 10240
net.core.somaxconn = 65535

# BBR Congestion Control y Ultra-Low Latency
net.ipv4.tcp_low_latency = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_fastopen = 3
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
EOF

sysctl --system > /dev/null

echo "[4/6] Fijando Gobernador de CPU en Performance..."
echo 'GOVERNOR="performance"' > /etc/default/cpufrequtils
systemctl restart cpufrequtils 2>/dev/null || true

echo "[5/6] Configurando sincronización horaria de microsegundos con Chrony..."
cat << 'EOF' > /etc/chrony/chrony.conf
server time.google.com iburst minpoll 4 maxpoll 4
server time.cloudflare.com iburst minpoll 4 maxpoll 4
makestep 1.0 3
rtcsync
EOF
systemctl restart chrony

echo "[6/6] Preparando entorno de la aplicación y servicio systemd..."
if [ "$CURRENT_DIR" != "$INSTALL_DIR" ]; then
    mkdir -p $INSTALL_DIR
    cp -r ./* $INSTALL_DIR/
fi

cd $INSTALL_DIR
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -r requirements.txt

if [ ! -f ".env" ]; then
    cp .env.example .env
fi

# Instalar servicio systemd
cp deployment/aureus-trading.service /etc/systemd/system/aureus-trading.service
systemctl daemon-reload
systemctl enable aureus-trading
systemctl restart aureus-trading

echo "================================================================="
echo "   INSTALACION Y CONFIGURACION COMPLETADAS EXITOSAMENTE          "
echo "================================================================="
echo "• Estado del servicio: systemctl status aureus-trading"
echo "• Logs en vivo:       journalctl -u aureus-trading -f -o cat"
echo "• Dashboard Web:      http://$(curl -s ifconfig.me || echo 'IP_DEL_VPS'):8000"
echo "================================================================="
