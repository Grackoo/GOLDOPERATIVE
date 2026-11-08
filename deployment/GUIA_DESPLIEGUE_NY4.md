# Guía de Despliegue Institucional en VPS (Equinix NY4)
## Configuración de Ultra-Baja Latencia (< 5ms) en Ubuntu 22.04 / 24.04 LTS

Esta guía detalla el endurecimiento del sistema operativo Linux, optimización del kernel TCP/IP y sincronización temporal a nivel de microsegundos requerida para operar el CFD de Oro (XAU/USD) con latencia inferior a **5 milisegundos** contra los motores de matching ECN situados en **Equinix NY4 (Secaucus, New Jersey)** o **Equinix LD4 (Slough, Reino Unido)**.

---

### 1. Especificaciones del Servidor VPS / Bare-Metal
- **Centro de Datos:** Equinix NY4 (Secaucus, NJ)
- **Cross-Connect Directo:** Fibra óptica hacia LMAX, Pepperstone, IC Markets, Tickmill o FXCM.
- **Hardware Recomendado:** Mínimo 4 vCPUs dedicados / 8 GB RAM / Almacenamiento NVMe SSD con Direct I/O.
- **Sistema Operativo:** Ubuntu 22.04 LTS o 24.04 LTS (versión Server minimal).

---

### 2. Script de Despliegue Automatizado (`deploy_ny4.sh`)

Para mayor comodidad, se ha incluido el script `deployment/deploy_ny4.sh`. Puede ejecutarse directamente como root para realizar todas las optimizaciones de forma desatendida:

```bash
chmod +x deployment/deploy_ny4.sh
sudo ./deployment/deploy_ny4.sh
```

---

### 3. Procedimiento Manual Paso a Paso

Si prefiere ejecutar o auditar cada comando manualmente, siga los pasos a continuación:

#### Paso 1: Actualizar paquetes del sistema
```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y build-essential curl git cpufrequtils chrony python3-pip python3-venv tzdata
```

#### Paso 2: Optimización del Kernel Linux (`/etc/sysctl.conf`)
Edite `/etc/sysctl.conf` para habilitar el algoritmo de congestión TCP BBR, buffers de red de alta velocidad y desactivar el arranque lento tras inactividad:

```ini
# Reducción de intercambio a disco y optimización WAL
vm.swappiness = 1
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10

# Memoria máxima para buffers de sockets TCP
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

# Modos de baja latencia institucional
net.ipv4.tcp_low_latency = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_fastopen = 3

# Control de congestión BBR (baja latencia y alto rendimiento)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
```

Aplique los cambios inmediatamente:
```bash
sudo sysctl -p
```

#### Paso 3: Fijar el Gobernador de CPU en Máximo Rendimiento
Evita el estrangulamiento de frecuencia de los núcleos:
```bash
echo 'GOVERNOR="performance"' | sudo tee /etc/default/cpufrequtils
sudo systemctl restart cpufrequtils
```

#### Paso 4: Ajustar Ring Buffers de la Interfaz de Red
```bash
# Reemplace eth0 por el nombre de su interfaz principal (ip link show)
NIC="eth0"
sudo ethtool -G $NIC rx 4096 tx 4096
sudo ethtool -K $NIC tso off gso off gro off
```

#### Paso 5: Sincronización Temporal de Microsegundos (`chrony`)
Garantiza que la apertura de Londres (03:00 EST) y Nueva York (08:00 EST) coincidan exactamente con el reloj atómico del broker:

Edite `/etc/chrony/chrony.conf`:
```ini
server time.google.com iburst minpoll 4 maxpoll 4
server time.cloudflare.com iburst minpoll 4 maxpoll 4

makestep 1.0 3
rtcsync
```

Reinicie el servicio y verifique la desviación:
```bash
sudo systemctl restart chrony
chronyc tracking
```

---

### 4. Instalación de la Aplicación y Servicio `systemd`

1. Clonar el repositorio en el directorio de producción:
```bash
sudo git clone <URL_REPOSITORIO> /opt/aureus-trading
cd /opt/aureus-trading
```

2. Crear el entorno virtual e instalar librerías:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

3. Configurar variables de entorno y credenciales:
```bash
cp .env.example .env
nano .env  # Ajuste el modo (PAPER / PRODUCTION), credenciales MT5/OANDA y parámetros
```

4. Instalar y arrancar el servicio `systemd`:
```bash
sudo cp deployment/aureus-trading.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aureus-trading
sudo systemctl start aureus-trading
```

5. Inspección de logs en tiempo real:
```bash
journalctl -u aureus-trading -f -o cat
```

---

### 5. Despliegue Alternativo con Docker

Si prefiere aislar el servicio mediante contenedores Docker:

```bash
cd /opt/aureus-trading/deployment
docker compose up -d --build
```

Comprobar logs:
```bash
docker logs -f aureus_trading_engine
```

Acceder al panel web desde cualquier navegador:
```
http://<IP_DE_SU_VPS>:8000
```
