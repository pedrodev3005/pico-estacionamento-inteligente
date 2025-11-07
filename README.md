# 🅿️ **Sistema de Monitoramento de Estacionamento Inteligente**

Projeto desenvolvido com **Raspberry Pi 3B**, **Sensores Ultrassônicos HC-SR04**, **Display OLED SSD1306**, LEDs e Buzzers para monitoramento de vagas de estacionamento em tempo real.

O sistema inclui uma **interface Web** que exibe o estado das vagas e permite acompanhamento remoto pela rede Wi-Fi.

---

### 👤 **Desenvolvido por**

[https://github.com/pedrodev3005](https://github.com/pedrodev3005)

---

[https://github.com/nicholas7821](https://github.com/nicholas7821)

## 🎯 **Objetivo do Projeto**

Criar um sistema embarcado capaz de:

- Detectar **se a vaga está livre ou ocupada** usando sensores ultrassônicos
- Sinalizar o estado de cada vaga através de:
    - **LED Verde** → Vaga **Livre**
    - **LED Vermelho** → Vaga **Ocupada**
    - **Buzzer** → Distância **muito próxima**
- Exibir informações do sistema e da rede no **display OLED**
- Permitir monitoramento via página Web acessível pela rede Wi-Fi

---

## 🧱 **Arquitetura do Sistema**

```
┌──────────────────-┐            I2C                   ┌──────────────────────────┐
│   Raspberry Pi    │ ----------------------->         │ Display OLED SSD1306     │
│      (BCM)        │                                  │ Status / Rede / IP       │
└───────┬───────────┘                                  └──────────────────────────┘
        │
        │  Sensores
        │
┌───────▼────────┐      ┌─────────────---┐
│ HC-SR04 Vaga 1 │      │ HC-SR04 Vaga 2 │
└───────┬────────┘      └───────┬──────--┘
        │                       │
        │                       │
 LEDs + Buzzers           LEDs + Buzzers
 (Sinalização)            (Sinalização)

        │ Wi-Fi
        ▼
┌──────────────────────────--┐
│ Interface Web (Flask/HTTP) │
│ Monitoramento em Tempo Real│
└──────────────────────────--┘

```

---

## 🌐 **Acesso Web**

Após conectar ao Wi-Fi, acesse via navegador:

```
http://<IP_DA_RASPBERRY>:8001

```

O IP é exibido automaticamente no **display OLED**.

---

## 🖥️ **Painel no Display OLED**

Quando **desconectado**:

→ Menu de escolha de rede + entrada de senha (navegado com botões)

Quando **conectado**:

→ Painel carrossel com:

- Nome da rede (SSID)
- Hostname
- IP + Porta Web
- Intensidade do sinal Wi-Fi
- Status do SSH e usuários ativos

---

## 🔧 Instalação

### 1) Clone o repositório:

```bash
git clone https://github.com/pedrodev3005/pico-estacionamento-inteligente

```

### 2) Habilite o I2C (se não estiver habilitado)

```bash
sudo raspi-config

```

### 3) Instale as dependências do display:

```bash
sudo apt install python3-pip python3-venv
python3 -m venv venv
source venv/bin/activate
pip install adafruit-circuitpython-ssd1306 pillow psutil

```

### 4) Crie o serviço para iniciar automaticamente no boot:

```bash
sudo systemctl enable monitor_sensor_web.service
sudo systemctl enable painel_wifi.service

```

---

## 🛠️ Hardware Utilizado

| Componente | Função |
| --- | --- |
| Raspberry Pi 3B | Unidade de Controle |
| 2x Sen. Ultrassônico HC-SR04 | Medição de distância das vagas |
| OLED SSD1306 I2C | Exibição de status do sistema |
| LEDs Verde/Vermelho | Indicação de vaga livre/ocupada |
| Buzzers | Sinal sonoro de manobra |
| Botões | Navegação no menu para Wi-Fi |

---

## 📁 Estrutura de Código

```
/projeto_embarcados
│
├─ monitor_sensor_web.py     → Servidor Web + Controle das Vagas
├─ painel_wifi.py            → Interface do Display OLED + Botões
│
└─ systemd/
   ├─ monitor_sensor_web.service
   └─ painel_wifi.service

```

---

## 📊 Dados Registrados

O sistema salva automaticamente:

- Histórico de distâncias
- Momentos de acionamento de LEDs
- Estados das vagas
- Eventos combinados

Arquivos em `/dados_sensor/`.

---

## ✅ Resultados

- Interface física simples e intuitiva ✅
- Monitoramento remoto via qualquer smartphone/computador ✅
- Sistema autônomo (inicia sozinho ao ligar) ✅
- Operação em tempo real ✅

---
