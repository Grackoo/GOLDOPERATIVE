# AUREUS-SMC Institutional VPS Deployment Guide
## Ultra Low-Latency Setup on Ubuntu 22.04 / 24.04 LTS (Equinix NY4)

This guide details the institutional hardening, OS kernel tuning, and network optimization required to achieve **< 5ms execution latency** with major ECN/STP Gold liquidity providers cross-connected inside **Equinix NY4 (Secaucus, NJ)** or **Equinix LD4 (Slough, UK)**.

---

### 1. Hardware & VPS Specifications
- **Datacenter:** Equinix NY4 (Secaucus, New Jersey)
- **Direct Cross-Connect:** Fiber patch to broker matching engine (e.g., LMAX, Pepperstone, IC Markets, Tickmill, FXCM)
- **Compute:** 4 vCPU / 8 GB RAM (Dedicated Bare-Metal or High-Frequency KVM)
- **OS:** Ubuntu 22.04 LTS or Ubuntu 24.04 LTS (Server minimal)
- **Storage:** NVMe SSD with Direct I/O

---

### 2. High-Performance Linux Kernel & Network Tuning

Execute the following commands to configure the TCP/IP stack for high-throughput, low-latency microsecond packet dispatching:

#### A. Kernel `sysctl.conf` Tuning
Append the following parameters to `/etc/sysctl.conf`:

```ini
# --- Virtual Memory & WAL I/O ---
vm.swappiness = 1
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10

# --- Low Latency TCP / Network Tuning ---
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.core.optmem_max = 2048576
net.core.netdev_max_backlog = 50000

# Increase maximum open sockets and backlog
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_max_syn_backlog = 10240
net.core.somaxconn = 65535

# Low-latency TCP optimizations
net.ipv4.tcp_low_latency = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_fastopen = 3

# TCP BBR Congestion Control (Google Low Latency)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
```

Apply immediately:
```bash
sudo sysctl -p
```

#### B. CPU Governor to Maximum Performance
Disable power-saving CPU throttling:
```bash
sudo apt-get install -y cpufrequtils
echo 'GOVERNOR="performance"' | sudo tee /etc/default/cpufrequtils
sudo systemctl restart cpufrequtils
```

#### C. NIC Ring Buffer Expansion
```bash
# Verify your primary network interface (e.g., eth0 or ens3)
NIC="eth0"
sudo ethtool -G $NIC rx 4096 tx 4096
sudo ethtool -K $NIC tso off gso off gro off
```

---

### 3. Microsecond Clock Synchronization (`chrony`)

Accurate session scheduling (03:00 EST London, 08:00 EST NY Open) requires sub-millisecond clock drift minimization:

```bash
sudo apt-get install -y chrony
```

Edit `/etc/chrony/chrony.conf`:
```ini
server time.google.com iburst minpoll 4 maxpoll 4
server time.cloudflare.com iburst minpoll 4 maxpoll 4

makestep 1.0 3
rtcsync
```

Restart and verify drift:
```bash
sudo systemctl restart chrony
chronyc tracking
```

---

### 4. Application Installation via `systemd` (Recommended for Native Performance)

1. Clone or upload the repository to `/opt/aureus-trading`:
```bash
sudo git clone <repo_url> /opt/aureus-trading
cd /opt/aureus-trading
```

2. Initialize isolated virtual environment:
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

3. Setup environment configuration:
```bash
cp .env.example .env
nano .env  # Enter broker credentials and adjust parameters
```

4. Install and enable the systemd service:
```bash
sudo cp deployment/aureus-trading.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aureus-trading
sudo systemctl start aureus-trading
```

5. Monitor live operational logs:
```bash
journalctl -u aureus-trading -f -o cat
```

---

### 5. Alternative: Containerized Deployment via Docker

If running across containerized environments:

```bash
cd /opt/aureus-trading/deployment
docker compose up -d --build
```

View container logs:
```bash
docker logs -f aureus_trading_engine
```

Access the real-time institutional dashboard:
```
http://<VPS_IP>:8000
```
