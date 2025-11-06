import http.server
import socketserver
import json
import threading
import time
import random
import os
import csv
import argparse
from datetime import datetime
from urllib.parse import parse_qs, urlparse

# Variável global para controle do LED
led_status = False
PORT = 8001

# ====================== Configuração de Estacionamento (2 vagas) ====================== #
# Sensores ultrassônicos (duas vagas)
S1_TRIGGER = 23  # Vaga 1 - Trigger
S1_ECHO = 24     # Vaga 1 - Echo
S2_TRIGGER = 14  # Vaga 2 - Trigger
S2_ECHO = 15     # Vaga 2 - Echo

# LEDs (vermelho/verde por vaga)
LED_VAGA1_VERMELHO = 25
LED_VAGA1_VERDE = 8
LED_VAGA2_VERMELHO = 7
LED_VAGA2_VERDE = 1  # Observação: GPIO 1 pode ser reservado em alguns modelos

# Polaridade (defina False se seu LED acende com nível baixo)
LED_VAGA1_RED_ACTIVE_HIGH = True
LED_VAGA1_GREEN_ACTIVE_HIGH = True
LED_VAGA2_RED_ACTIVE_HIGH = True
LED_VAGA2_GREEN_ACTIVE_HIGH = True

# Polaridade dos buzzers (alterar para False se acionam em LOW)
BUZZER_VAGA1_ACTIVE_HIGH = True
BUZZER_VAGA2_ACTIVE_HIGH = True

# Buzzers por vaga
BUZZER_VAGA1 = 12
BUZZER_VAGA2 = 13

# Thresholds (ajuste conforme instalação)
THRESHOLD_OCUPADA_CM = 40.0   # abaixo disso considera ocupada
THRESHOLD_MUITO_PROXIMO_CM = 10.0  # abaixo disso emite bip

# Simulação do sensor HC-SR04
class SensorSimulado:
    def _init_(self):
        self.valor_base = 20.0
        self.direcao = 1
        
    def medir_distancia(self):
        # Simula uma leitura oscilante entre 10 e 30 cm
        self.valor_base += 0.5 * self.direcao + random.uniform(-1, 1)
        if self.valor_base > 30:
            self.direcao = -1
        elif self.valor_base < 10:
            self.direcao = 1
        return round(self.valor_base, 2)
    
    def cleanup(self):
        pass

# Tenta importar a classe real do sensor (se estiver em um Raspberry Pi)
try:
    import RPi.GPIO as GPIO
    
    # Configuração do LED
    LED_PIN = 18  # Pino GPIO para o LED
    
    class SensorHCSR04:
        def _init_(self, trigger_pin=23, echo_pin=24):
            # Configuração do GPIO
            self.PIN_TRIGGER = trigger_pin
            self.PIN_ECHO = echo_pin
            
            # Use BCM pin numbering
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            # Configura os pinos
            GPIO.setup(self.PIN_TRIGGER, GPIO.OUT)
            GPIO.setup(self.PIN_ECHO, GPIO.IN)
            
            # Configura o pino do LED
            GPIO.setup(LED_PIN, GPIO.OUT)
            GPIO.output(LED_PIN, GPIO.LOW)  # Inicia desligado
            
            # Inicializa com valor baixo
            GPIO.output(self.PIN_TRIGGER, GPIO.LOW)
            time.sleep(0.1)  # Pequena pausa para estabilizar
            
        def medir_distancia(self):
            # Garante que o Trigger começa em nível baixo
            GPIO.output(self.PIN_TRIGGER, GPIO.LOW)
            time.sleep(0.05)  # Pequena pausa
            
            # Envia o pulso de trigger (10 microssegundos)
            GPIO.output(self.PIN_TRIGGER, GPIO.HIGH)
            time.sleep(0.00001)  # 10 us
            GPIO.output(self.PIN_TRIGGER, GPIO.LOW)
            
            pulse_start_time = time.time()
            pulse_end_time = time.time()
            timeout_start = time.time()
            
            # Guarda o tempo de início do pulso de echo
            while GPIO.input(self.PIN_ECHO) == 0:
                pulse_start_time = time.time()
                # Adiciona timeout para evitar loop infinito
                if time.time() - timeout_start > 0.1:  # Timeout de 100ms
                    return None  # Retorna None em caso de erro
            
            timeout_start = time.time()  # Reseta timeout
            
            # Guarda o tempo de fim do pulso de echo
            while GPIO.input(self.PIN_ECHO) == 1:
                pulse_end_time = time.time()
                # Adiciona timeout para evitar loop infinito
                if time.time() - timeout_start > 0.1:  # Timeout de 100ms
                    return None  # Retorna None em caso de erro
            
            # Calcula a duração do pulso
            pulse_duration = pulse_end_time - pulse_start_time
            
            # Calcula a distância (velocidade do som ~34300 cm/s)
            # Distância = (Tempo * Velocidade) / 2
            distance = (pulse_duration * 34300) / 2
            
            return round(distance, 2)
        
        def cleanup(self):
            GPIO.cleanup()
    
    sensor = SensorHCSR04()
    print("Sensor HC-SR04 inicializado com sucesso!")
    
except (ImportError, RuntimeError):
    print("Executando em modo de simulação (sem GPIO)")
    sensor = SensorSimulado()

# Inicialização dos pinos para estacionamento quando em Raspberry Pi
try:
    import RPi.GPIO as _GPIO_check
    # Configuração de pinos de sensores e atuadores de estacionamento
    _GPIO_check.setmode(_GPIO_check.BCM)
    _GPIO_check.setwarnings(False)
    # Sensores
    _GPIO_check.setup(S1_TRIGGER, _GPIO_check.OUT)
    _GPIO_check.setup(S1_ECHO, _GPIO_check.IN)
    _GPIO_check.setup(S2_TRIGGER, _GPIO_check.OUT)
    _GPIO_check.setup(S2_ECHO, _GPIO_check.IN)
    # Atuadores
    for pin in [LED_VAGA1_VERMELHO, LED_VAGA1_VERDE, LED_VAGA2_VERMELHO, LED_VAGA2_VERDE,
                BUZZER_VAGA1, BUZZER_VAGA2]:
        try:
            _GPIO_check.setup(pin, _GPIO_check.OUT, initial=_GPIO_check.LOW)
        except Exception as e:
            print(f"Aviso: falha ao configurar GPIO {pin}: {e}")
except Exception:
    # Em ambiente de simulação (Windows), essa etapa é ignorada
    pass

# Variáveis globais
leituras_historico = []
MAX_HISTORICO = 20  # Reduzido para economizar memória
intervalo_leitura = 2.0  # Aumentado para reduzir carga no sistema

# Cache de estado das vagas para servir via API sem depender da página aberta
estado_vagas_cache = {
    'timestamp': None,
    'vaga1': {
        'distancia': None,
        'estado': 'desconhecido',
        'muito_proximo': False,
        'led_vermelho': False,
        'led_verde': False,
        'buzzer': False,
    },
    'vaga2': {
        'distancia': None,
        'estado': 'desconhecido',
        'muito_proximo': False,
        'led_vermelho': False,
        'led_verde': False,
        'buzzer': False,
    }
}
cache_vagas_lock = threading.Lock()
intervalo_estacionamento = 1.5

# Estado de simulação para duas vagas
sim_vaga1 = {'valor_base': 35.0, 'direcao': -1}
sim_vaga2 = {'valor_base': 25.0, 'direcao': 1}

# Configuração para armazenamento em CSV
DIRETORIO_DADOS = "dados_sensor"
ARQUIVO_LEITURAS = os.path.join(DIRETORIO_DADOS, "leituras_sensor.csv")
ARQUIVO_ACOES_LED = os.path.join(DIRETORIO_DADOS, "acoes_led.csv")
ARQUIVO_EVENTOS = os.path.join(DIRETORIO_DADOS, "historico_completo.csv")
ARQUIVO_VAGA1 = os.path.join(DIRETORIO_DADOS, "leituras_vaga1.csv")
ARQUIVO_VAGA2 = os.path.join(DIRETORIO_DADOS, "leituras_vaga2.csv")
ARQUIVO_UNIFICADO = os.path.join(DIRETORIO_DADOS, "historico_unificado.csv")

# Criar diretório de dados se não existir
if not os.path.exists(DIRETORIO_DADOS):
    os.makedirs(DIRETORIO_DADOS)

# Inicializar arquivos CSV se não existirem
def inicializar_arquivos_csv():
    # Arquivo de leituras do sensor
    if not os.path.exists(ARQUIVO_LEITURAS):
        with open(ARQUIVO_LEITURAS, 'w', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(['timestamp', 'distancia_cm'])
    
    # Arquivo de ações do LED
    if not os.path.exists(ARQUIVO_ACOES_LED):
        with open(ARQUIVO_ACOES_LED, 'w', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(['timestamp', 'acao', 'estado'])
    
    # Arquivo combinado de eventos (leituras + LED)
    if not os.path.exists(ARQUIVO_EVENTOS):
        with open(ARQUIVO_EVENTOS, 'w', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(['timestamp', 'tipo', 'descricao', 'valor'])
    # Arquivo unificado de leituras e acionamentos
    if not os.path.exists(ARQUIVO_UNIFICADO):
        with open(ARQUIVO_UNIFICADO, 'w', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(['timestamp', 'tipo', 'origem', 'distancia_cm', 'estado', 'muito_proximo', 'acao_led', 'estado_led'])
    # Arquivos de leituras por vaga
    if not os.path.exists(ARQUIVO_VAGA1):
        with open(ARQUIVO_VAGA1, 'w', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(['timestamp', 'distancia_cm', 'estado', 'muito_proximo'])
    if not os.path.exists(ARQUIVO_VAGA2):
        with open(ARQUIVO_VAGA2, 'w', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(['timestamp', 'distancia_cm', 'estado', 'muito_proximo'])

# Função para registrar leitura do sensor
def registrar_leitura(distancia, timestamp):
    # Registra no arquivo específico de leituras
    with open(ARQUIVO_LEITURAS, 'a', newline='') as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow([timestamp, distancia])
    
    # Registra no arquivo combinado de eventos
    with open(ARQUIVO_EVENTOS, 'a', newline='') as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow([timestamp, 'sensor', 'distancia_cm', distancia])
    # Unificado
    try:
        with open(ARQUIVO_UNIFICADO, 'a', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow([timestamp, 'leitura', 'sensor', distancia, '', '', '', ''])
    except Exception as e:
        print(f"Erro ao registrar no unificado (sensor): {e}")

# Função para registrar ação do LED
def registrar_acao_led(estado, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Registra no arquivo específico de ações do LED
    with open(ARQUIVO_ACOES_LED, 'a', newline='') as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow([timestamp, 'alteracao', 'ligado' if estado else 'desligado'])
    
    # Registra no arquivo combinado de eventos
    with open(ARQUIVO_EVENTOS, 'a', newline='') as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow([timestamp, 'led', 'estado', 'ligado' if estado else 'desligado'])
    # Unificado
    try:
        with open(ARQUIVO_UNIFICADO, 'a', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow([timestamp, 'acao', 'led', '', '', '', 'toggle', 'ligado' if estado else 'desligado'])
    except Exception as e:
        print(f"Erro ao registrar no unificado (led): {e}")

# Registra leitura de uma vaga em CSV e no histórico consolidado
def registrar_leitura_vaga(vaga_id, distancia, estado, muito_proximo, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    linha = [timestamp, distancia if distancia is not None else '', estado, 'sim' if muito_proximo else 'nao']
    try:
        if vaga_id == 1:
            with open(ARQUIVO_VAGA1, 'a', newline='') as arquivo:
                csv.writer(arquivo).writerow(linha)
        else:
            with open(ARQUIVO_VAGA2, 'a', newline='') as arquivo:
                csv.writer(arquivo).writerow(linha)
    except Exception as e:
        print(f"Erro ao registrar CSV da vaga {vaga_id}: {e}")
    # Também registra no consolidado
    try:
        with open(ARQUIVO_EVENTOS, 'a', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow([timestamp, f'vaga{vaga_id}', 'distancia_cm', distancia if distancia is not None else ''])
    except Exception as e:
        print(f"Erro ao registrar eventos da vaga {vaga_id}: {e}")
    # Também registra no unificado
    try:
        with open(ARQUIVO_UNIFICADO, 'a', newline='') as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow([
                timestamp,
                'leitura',
                f'vaga{vaga_id}',
                distancia if distancia is not None else '',
                estado,
                'sim' if muito_proximo else 'nao',
                '',
                ''
            ])
    except Exception as e:
        print(f"Erro ao registrar no unificado da vaga {vaga_id}: {e}")

# ====================== Funções de estacionamento ====================== #
def medir_distancia_parking(trigger_pin, echo_pin):
    """Mede a distância via GPIO com timeouts. Retorna None em falha."""
    try:
        import RPi.GPIO as GPIO
    except Exception:
        # Sem GPIO: usa simulação conforme a vaga
        if trigger_pin == S1_TRIGGER:
            base = sim_vaga1['valor_base']
            dirc = sim_vaga1['direcao']
            base += 0.8 * dirc + random.uniform(-2, 2)
            if base > 60:
                sim_vaga1['direcao'] = -1
            elif base < 5:
                sim_vaga1['direcao'] = 1
            sim_vaga1['valor_base'] = base
            return round(base, 2)
        else:
            base = sim_vaga2['valor_base']
            dirc = sim_vaga2['direcao']
            base += 0.6 * dirc + random.uniform(-2, 2)
            if base > 60:
                sim_vaga2['direcao'] = -1
            elif base < 5:
                sim_vaga2['direcao'] = 1
            sim_vaga2['valor_base'] = base
            return round(base, 2)

    # Com GPIO real
    GPIO.output(trigger_pin, GPIO.LOW)
    time.sleep(0.2)
    GPIO.output(trigger_pin, GPIO.HIGH)
    time.sleep(0.00001)
    GPIO.output(trigger_pin, GPIO.LOW)

    pulse_start_time = time.time()
    pulse_end_time = time.time()

    # Aguardando início do echo
    timeout_start = time.time()
    while GPIO.input(echo_pin) == 0:
        pulse_start_time = time.time()
        if time.time() - timeout_start > 0.1:
            return None

    # Aguardando fim do echo
    timeout_start = time.time()
    while GPIO.input(echo_pin) == 1:
        pulse_end_time = time.time()
        if time.time() - timeout_start > 0.1:
            return None

    pulse_duration = pulse_end_time - pulse_start_time
    distance = (pulse_duration * 34300) / 2
    return round(distance, 2)


def write_output(pin, turn_on, active_high=True):
    try:
        import RPi.GPIO as GPIO
    except Exception:
        return  # sem GPIO, ignora
    if active_high:
        GPIO.output(pin, GPIO.HIGH if turn_on else GPIO.LOW)
    else:
        GPIO.output(pin, GPIO.LOW if turn_on else GPIO.HIGH)


def atualizar_atuadores(dist_cm, led_vermelho, led_verde, buzzer):
    """Atualiza LED e buzzer de uma vaga a partir da distância medida."""
    if dist_cm is None:
        write_output(led_vermelho, False, True)
        write_output(led_verde, False, True)
        write_output(buzzer, False, True)
        return "falha"

    ocupada = dist_cm < THRESHOLD_OCUPADA_CM
    muito_proximo = dist_cm < THRESHOLD_MUITO_PROXIMO_CM

    # LEDs por vaga
    if led_vermelho == LED_VAGA1_VERMELHO and led_verde == LED_VAGA1_VERDE:
        write_output(LED_VAGA1_VERMELHO, ocupada, LED_VAGA1_RED_ACTIVE_HIGH)
        write_output(LED_VAGA1_VERDE, not ocupada, LED_VAGA1_GREEN_ACTIVE_HIGH)
    elif led_vermelho == LED_VAGA2_VERMELHO and led_verde == LED_VAGA2_VERDE:
        write_output(LED_VAGA2_VERMELHO, ocupada, LED_VAGA2_RED_ACTIVE_HIGH)
        write_output(LED_VAGA2_VERDE, not ocupada, LED_VAGA2_GREEN_ACTIVE_HIGH)
    else:
        write_output(led_vermelho, ocupada, True)
        write_output(led_verde, not ocupada, True)

    # Buzzer
    if buzzer == BUZZER_VAGA1:
        write_output(BUZZER_VAGA1, muito_proximo, BUZZER_VAGA1_ACTIVE_HIGH)
    elif buzzer == BUZZER_VAGA2:
        write_output(BUZZER_VAGA2, muito_proximo, BUZZER_VAGA2_ACTIVE_HIGH)
    else:
        write_output(buzzer, muito_proximo, True)

    # Retorna estado textual da vaga
    return "ocupada" if ocupada else "livre"

# Loop contínuo para ler as duas vagas, acionar atuadores e atualizar o cache
def loop_estacionamento():
    global estado_vagas_cache
    while True:
        try:
            d1 = medir_distancia_parking(S1_TRIGGER, S1_ECHO)
            d2 = medir_distancia_parking(S2_TRIGGER, S2_ECHO)
            estado1 = atualizar_atuadores(d1, LED_VAGA1_VERMELHO, LED_VAGA1_VERDE, BUZZER_VAGA1)
            estado2 = atualizar_atuadores(d2, LED_VAGA2_VERMELHO, LED_VAGA2_VERDE, BUZZER_VAGA2)
            prox1 = (d1 is not None) and (d1 < THRESHOLD_MUITO_PROXIMO_CM)
            prox2 = (d2 is not None) and (d2 < THRESHOLD_MUITO_PROXIMO_CM)

            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # Registra CSV por vaga
            registrar_leitura_vaga(1, d1, estado1, prox1, ts)
            registrar_leitura_vaga(2, d2, estado2, prox2, ts)

            # Atualiza cache usado pelo endpoint
            with cache_vagas_lock:
                estado_vagas_cache['timestamp'] = ts
                estado_vagas_cache['vaga1'] = {
                    'distancia': None if d1 is None else float(round(d1, 2)),
                    'estado': estado1,
                    'muito_proximo': prox1,
                    'led_vermelho': True if (d1 is not None and d1 < THRESHOLD_OCUPADA_CM) else False,
                    'led_verde': True if (d1 is not None and d1 >= THRESHOLD_OCUPADA_CM) else False,
                    'buzzer': True if prox1 else False,
                }
                estado_vagas_cache['vaga2'] = {
                    'distancia': None if d2 is None else float(round(d2, 2)),
                    'estado': estado2,
                    'muito_proximo': prox2,
                    'led_vermelho': True if (d2 is not None and d2 < THRESHOLD_OCUPADA_CM) else False,
                    'led_verde': True if (d2 is not None and d2 >= THRESHOLD_OCUPADA_CM) else False,
                    'buzzer': True if prox2 else False,
                }
        except Exception as e:
            print(f"Erro no loop de estacionamento: {e}")
        finally:
            time.sleep(intervalo_estacionamento)

# HTML da página principal - Versão simplificada
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Estacionamento Inteligente</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #2196F3;
            text-align: center;
        }
        .alerta {
            margin: 20px 0;
            padding: 12px;
            border-radius: 6px;
            background-color: #ffebee;
            color: #b71c1c;
            border: 1px solid #ffcdd2;
            text-align: center;
            display: none;
            font-weight: bold;
        }
        footer {
            margin-top: 30px;
            text-align: center;
            color: #757575;
            font-size: 14px;
        }
        .historico {
            margin-top: 30px;
            border-top: 1px solid #ddd;
            padding-top: 20px;
        }
        .historico h2 {
            color: #2196F3;
            text-align: center;
            margin-bottom: 15px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background-color: #f2f2f2;
            color: #333;
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
</head>
<body>
    <div class="container">
        <h1>Estacionamento Inteligente</h1>

        <div class="historico" style="margin-top: 10px;">
            <h2>Controle do LED</h2>
            <div style="display:flex; gap:12px; align-items:center; justify-content:center;">
                <div>Estado do LED: <span id="led-estado">--</span></div>
                <button id="led-toggle" style="background:#ff9800;color:#fff;padding:6px 10px;border:none;border-radius:4px;cursor:pointer;">Ligar LED</button>
                <a href="/download/led" style="background:#795548;color:#fff;padding:6px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Baixar CSV LED</a>
                <a href="/download/unificado" style="background:#607D8B;color:#fff;padding:6px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Baixar CSV Unificado</a>
            </div>
        </div>
        
        <div id="alerta-proximidade" class="alerta">Alerta: veículo muito próximo em uma das vagas!</div>

        <div class="historico">
            <h2>Estacionamento (2 vagas)</h2>
            <div id="parking-status" style="display:flex; gap:12px; justify-content:center;">
                <div style="flex:1; padding:12px; border:1px solid #ddd; border-radius:6px;">
                    <h3 style="margin:0 0 8px 0; color:#333;">Vaga 1</h3>
                    <div>Distância: <span id="vaga1-dist">--</span> cm</div>
                    <div>Estado: <span id="vaga1-estado">--</span></div>
                    <div>Muito próximo: <span id="vaga1-prox">--</span></div>
                    <div>LED vermelho: <span id="vaga1-led-v">--</span></div>
                    <div>LED verde: <span id="vaga1-led-g">--</span></div>
                    <div>Buzzer: <span id="vaga1-buzzer">--</span></div>
                    <canvas id="chart-vaga1" width="300" height="120" style="margin-top:8px;border-radius:4px;background:#000;"></canvas>
                    <div style="margin-top:8px; text-align:right;">
                        <a href="/download/leituras_vaga1.csv" style="background:#2196F3;color:#fff;padding:6px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Baixar CSV Vaga 1</a>
                    </div>
                </div>
                <div style="flex:1; padding:12px; border:1px solid #ddd; border-radius:6px;">
                    <h3 style="margin:0 0 8px 0; color:#333;">Vaga 2</h3>
                    <div>Distância: <span id="vaga2-dist">--</span> cm</div>
                    <div>Estado: <span id="vaga2-estado">--</span></div>
                    <div>Muito próximo: <span id="vaga2-prox">--</span></div>
                    <div>LED vermelho: <span id="vaga2-led-v">--</span></div>
                    <div>LED verde: <span id="vaga2-led-g">--</span></div>
                    <div>Buzzer: <span id="vaga2-buzzer">--</span></div>
                    <canvas id="chart-vaga2" width="300" height="120" style="margin-top:8px;border-radius:4px;background:#000;"></canvas>
                    <div style="margin-top:8px; text-align:right;">
                        <a href="/download/leituras_vaga2.csv" style="background:#4CAF50;color:#fff;padding:6px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Baixar CSV Vaga 2</a>
                    </div>
                </div>
            </div>
        </div>
        
        <footer>
            Sistema de Monitoramento do Sensor HC-SR04 - Raspberry Pi 3B (Versão Lite)
        </footer>
        
        
    </div>

    <script>
        // Elementos da interface
        const alerta = document.getElementById('alerta-proximidade');
        const vaga1Dist = document.getElementById('vaga1-dist');
        const vaga1Estado = document.getElementById('vaga1-estado');
        const vaga1Prox = document.getElementById('vaga1-prox');
        const vaga2Dist = document.getElementById('vaga2-dist');
        const vaga2Estado = document.getElementById('vaga2-estado');
        const vaga2Prox = document.getElementById('vaga2-prox');
        const chartVaga1 = document.getElementById('chart-vaga1');
        const chartVaga2 = document.getElementById('chart-vaga2');
        const v1LedV = document.getElementById('vaga1-led-v');
        const v1LedG = document.getElementById('vaga1-led-g');
        const v1Buzzer = document.getElementById('vaga1-buzzer');
        const v2LedV = document.getElementById('vaga2-led-v');
        const v2LedG = document.getElementById('vaga2-led-g');
        const v2Buzzer = document.getElementById('vaga2-buzzer');
        const ledEstado = document.getElementById('led-estado');
        const ledToggle = document.getElementById('led-toggle');
        const dadosVaga1 = [];
        const dadosVaga2 = [];
        let startTime = Date.now();
        const MAX_PONTOS = 40;
        let chart1 = null;
        let chart2 = null;

        // Inicializa a página
        window.addEventListener('load', function() {
            atualizarEstacionamento();
            inicializarGraficos();
            atualizarLedStatus();

            // Atualiza periodicamente apenas o estacionamento
            setInterval(atualizarEstacionamento, 1500);
            setInterval(atualizarLedStatus, 2000);
            ledToggle.addEventListener('click', function() {
                const ligar = ledToggle.textContent.includes('Ligar');
                fetch('/api/led?estado=' + (ligar ? 1 : 0))
                    .then(r => r.json())
                    .then(() => atualizarLedStatus())
                    .catch(err => console.error('Erro ao alternar LED:', err));
            });
        });
        
        // Atualização do status das vagas de estacionamento
        function atualizarEstacionamento() {
            fetch('/api/parking/status')
                .then(response => response.json())
                .then(data => {
                    vaga1Dist.textContent = data.vaga1.distancia !== null ? data.vaga1.distancia.toFixed(2) : '--';
                    vaga1Estado.textContent = data.vaga1.estado;
                    vaga1Prox.textContent = data.vaga1.muito_proximo ? 'Sim' : 'Não';
                    v1LedV.textContent = data.vaga1.led_vermelho ? 'Ligado' : 'Desligado';
                    v1LedG.textContent = data.vaga1.led_verde ? 'Ligado' : 'Desligado';
                    v1Buzzer.textContent = data.vaga1.buzzer ? 'Ligado' : 'Desligado';
                    vaga2Dist.textContent = data.vaga2.distancia !== null ? data.vaga2.distancia.toFixed(2) : '--';
                    vaga2Estado.textContent = data.vaga2.estado;
                    vaga2Prox.textContent = data.vaga2.muito_proximo ? 'Sim' : 'Não';
                    v2LedV.textContent = data.vaga2.led_vermelho ? 'Ligado' : 'Desligado';
                    v2LedG.textContent = data.vaga2.led_verde ? 'Ligado' : 'Desligado';
                    v2Buzzer.textContent = data.vaga2.buzzer ? 'Ligado' : 'Desligado';
                    // Exibe alerta indicando quais vagas estão muito próximas
                    const vagasProximas = [];
                    if (data.vaga1.muito_proximo) vagasProximas.push('Vaga 1');
                    if (data.vaga2.muito_proximo) vagasProximas.push('Vaga 2');
                    if (vagasProximas.length > 0) {
                        alerta.textContent = 'Alerta: ' + vagasProximas.join(' e ') + ' muito próxima(s)!';
                        alerta.style.display = 'block';
                    } else {
                        alerta.style.display = 'none';
                    }

                    // Atualiza gráficos Chart.js em linha com eixo de tempo
                    const t = new Date();
                    if (typeof data.vaga1.distancia === 'number') {
                        dadosVaga1.push({ x: t, y: data.vaga1.distancia });
                        if (dadosVaga1.length > MAX_PONTOS) dadosVaga1.shift();
                        chart1.data.datasets[0].data = dadosVaga1.slice();
                        chart1.update('none');
                    }
                    if (typeof data.vaga2.distancia === 'number') {
                        dadosVaga2.push({ x: t, y: data.vaga2.distancia });
                        if (dadosVaga2.length > MAX_PONTOS) dadosVaga2.shift();
                        chart2.data.datasets[0].data = dadosVaga2.slice();
                        chart2.update('none');
                    }
                })
                .catch(err => {
                    console.error('Erro ao obter status de estacionamento:', err);
                });
        }

        function inicializarGraficos() {
            chart1 = new Chart(chartVaga1.getContext('2d'), {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'ultrassom variação tempo X mm',
                        data: [],
                        borderColor: '#F44336',
                        borderWidth: 2.5,
                        pointRadius: 0,
                        tension: 0.2,
                        fill: false,
                    }]
                },
                options: {
                    responsive: false,
                    plugins: {
                        legend: { display: false, labels: { color: '#ddd' } },
                        title: { display: true, text: 'ultrassom variação tempo X mm', color: '#ddd' },
                        tooltip: { enabled: true }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: { unit: 'second', displayFormats: { second: 'HH:mm:ss' } },
                            title: { display: true, text: 'Tempo', color: '#ddd' },
                            grid: { display: false },
                            ticks: { color: '#ddd', maxRotation: 45, minRotation: 30 }
                        },
                        y: {
                            title: { display: true, text: 'cm', color: '#ddd' },
                            grid: { display: true, color: '#aaa', lineWidth: 1.2 },
                            ticks: { color: '#ddd' },
                            beginAtZero: true
                        }
                    }
                }
            });
            chart2 = new Chart(chartVaga2.getContext('2d'), {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'ultrassom variação tempo X mm',
                        data: [],
                        borderColor: '#2196F3',
                        borderWidth: 2.5,
                        pointRadius: 0,
                        tension: 0.2,
                        fill: false,
                    }]
                },
                options: {
                    responsive: false,
                    plugins: {
                        legend: { display: false, labels: { color: '#ddd' } },
                        title: { display: true, text: 'ultrassom variação tempo X mm', color: '#ddd' },
                        tooltip: { enabled: true }
                    },
                    scales: {
                        x: {
                            type: 'time',
                            time: { unit: 'second', displayFormats: { second: 'HH:mm:ss' } },
                            title: { display: true, text: 'Tempo', color: '#ddd' },
                            grid: { display: false },
                            ticks: { color: '#ddd', maxRotation: 45, minRotation: 30 }
                        },
                        y: {
                            title: { display: true, text: 'cm', color: '#ddd' },
                            grid: { display: true, color: '#aaa', lineWidth: 1.2 },
                            ticks: { color: '#ddd' },
                            beginAtZero: true
                        }
                    }
                }
            });
        }

        function atualizarLedStatus() {
            fetch('/api/led/status')
                .then(r => r.json())
                .then(d => {
                    ledEstado.textContent = d.estado ? 'Ligado' : 'Desligado';
                    ledToggle.textContent = d.estado ? 'Desligar LED' : 'Ligar LED';
                })
                .catch(err => console.error('Erro ao obter estado do LED:', err));
        }
    </script>
</body>
</html>
"""

# Classe para o servidor HTTP
class SensorHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        global led_status
        
        if path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode())
            return
        
        elif path == '/api/leitura':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # Obter leitura atual
            distancia = sensor.medir_distancia()
            timestamp = datetime.now().strftime('%H:%M:%S')
            
            # Adicionar ao histórico
            leitura = {'valor': distancia, 'timestamp': timestamp}
            leituras_historico.append(leitura)
            
            # Limitar tamanho do histórico
            if len(leituras_historico) > MAX_HISTORICO:
                leituras_historico.pop(0)
            
            self.wfile.write(json.dumps(leitura).encode())
            return
        
        elif path == '/api/historico':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # Retorna as últimas leituras (já estão em memória)
            self.wfile.write(json.dumps(leituras_historico).encode())
            return
        
        elif path == '/api/historico/led':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            historico_led = []
            try:
                if os.path.exists(ARQUIVO_ACOES_LED):
                    with open(ARQUIVO_ACOES_LED, 'r', newline='') as arquivo:
                        leitor = csv.reader(arquivo)
                        next(leitor, None)  # pula cabeçalho
                        linhas = list(leitor)[-50:]
                        for linha in linhas:
                            if len(linha) >= 3:
                                historico_led.append({
                                    'timestamp': linha[0],
                                    'acao': linha[1],
                                    'estado': linha[2]
                                })
            except Exception as e:
                print(f"Erro ao ler histórico do LED: {e}")
            
            self.wfile.write(json.dumps(historico_led).encode())
            return
        
        elif path == '/api/historico/eventos':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            historico_eventos = []
            try:
                if os.path.exists(ARQUIVO_EVENTOS):
                    with open(ARQUIVO_EVENTOS, 'r', newline='') as arquivo:
                        leitor = csv.reader(arquivo)
                        next(leitor, None)
                        linhas = list(leitor)[-100:]
                        for linha in linhas:
                            if len(linha) >= 4:
                                historico_eventos.append({
                                    'timestamp': linha[0],
                                    'tipo': linha[1],
                                    'descricao': linha[2],
                                    'valor': linha[3]
                                })
            except Exception as e:
                print(f"Erro ao ler histórico combinado: {e}")
            
            self.wfile.write(json.dumps(historico_eventos).encode())
            return
        
        elif path == '/api/parking/status':
            # Tenta servir do cache preenchido pelo loop em segundo plano
            with cache_vagas_lock:
                cache_snapshot = {
                    'timestamp': estado_vagas_cache.get('timestamp'),
                    'vaga1': dict(estado_vagas_cache.get('vaga1', {})),
                    'vaga2': dict(estado_vagas_cache.get('vaga2', {})),
                }

            if cache_snapshot['timestamp']:
                payload = cache_snapshot
            else:
                # Fallback: ler uma vez diretamente se o cache ainda não estiver pronto
                d1 = medir_distancia_parking(S1_TRIGGER, S1_ECHO)
                d2 = medir_distancia_parking(S2_TRIGGER, S2_ECHO)
                estado1 = atualizar_atuadores(d1, LED_VAGA1_VERMELHO, LED_VAGA1_VERDE, BUZZER_VAGA1)
                estado2 = atualizar_atuadores(d2, LED_VAGA2_VERMELHO, LED_VAGA2_VERDE, BUZZER_VAGA2)
                prox1 = (d1 is not None) and (d1 < THRESHOLD_MUITO_PROXIMO_CM)
                prox2 = (d2 is not None) and (d2 < THRESHOLD_MUITO_PROXIMO_CM)

                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                registrar_leitura_vaga(1, d1, estado1, prox1, ts)
                registrar_leitura_vaga(2, d2, estado2, prox2, ts)

                payload = {
                    'timestamp': ts,
                    'vaga1': {
                        'distancia': None if d1 is None else float(round(d1, 2)),
                        'estado': estado1,
                        'muito_proximo': prox1,
                        'led_vermelho': True if (d1 is not None and d1 < THRESHOLD_OCUPADA_CM) else False,
                        'led_verde': True if (d1 is not None and d1 >= THRESHOLD_OCUPADA_CM) else False,
                        'buzzer': True if prox1 else False
                    },
                    'vaga2': {
                        'distancia': None if d2 is None else float(round(d2, 2)),
                        'estado': estado2,
                        'muito_proximo': prox2,
                        'led_vermelho': True if (d2 is not None and d2 < THRESHOLD_OCUPADA_CM) else False,
                        'led_verde': True if (d2 is not None and d2 >= THRESHOLD_OCUPADA_CM) else False,
                        'buzzer': True if prox2 else False
                    }
                }

                # Atualiza o cache para futuras respostas
                with cache_vagas_lock:
                    estado_vagas_cache.update(payload)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
            return
        
        elif path == '/api/led':
            
            # Obter parâmetros da URL
            query = parse_qs(parsed_path.query)
            estado = int(query.get('estado', ['0'])[0])
            
            # Atualizar estado do LED
            led_status = (estado == 1)
            
            # Controlar o LED real na Raspberry Pi
            try:
                import RPi.GPIO as GPIO
                GPIO.output(LED_PIN, GPIO.HIGH if led_status else GPIO.LOW)
                print(f"LED {'ligado' if led_status else 'desligado'}")
            except (ImportError, NameError):
                # Em modo de simulação, apenas exibe mensagem
                print(f"Simulação: LED {'ligado' if led_status else 'desligado'}")
            
            # Registrar ação no histórico CSV
            registrar_acao_led(led_status)
            
            # Enviar resposta
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'estado': 1 if led_status else 0}).encode())
            return

        elif path == '/api/led/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'estado': 1 if led_status else 0}).encode())
            return
        
        # Endpoints de download dos arquivos CSV
        elif path == '/download/leituras':
            if os.path.exists(ARQUIVO_LEITURAS):
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', 'attachment; filename="leituras_sensor.csv"')
                    self.end_headers()
                    with open(ARQUIVO_LEITURAS, 'rb') as f:
                        self.wfile.write(f.read())
                except Exception as e:
                    print(f"Erro ao enviar leituras CSV: {e}")
                    self.send_error(500, "Erro ao enviar arquivo")
            else:
                self.send_error(404, "Arquivo de leituras não encontrado")
            return
        elif path == '/download/leituras_vaga1.csv':
            if os.path.exists(ARQUIVO_VAGA1):
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', 'attachment; filename="leituras_vaga1.csv"')
                    self.end_headers()
                    with open(ARQUIVO_VAGA1, 'rb') as f:
                        self.wfile.write(f.read())
                except Exception as e:
                    print(f"Erro ao enviar leituras CSV da vaga 1: {e}")
                    self.send_error(500, "Erro ao enviar arquivo")
            else:
                self.send_error(404, "Arquivo de leituras da vaga 1 não encontrado")
            return
        elif path == '/download/leituras_vaga2.csv':
            if os.path.exists(ARQUIVO_VAGA2):
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', 'attachment; filename="leituras_vaga2.csv"')
                    self.end_headers()
                    with open(ARQUIVO_VAGA2, 'rb') as f:
                        self.wfile.write(f.read())
                except Exception as e:
                    print(f"Erro ao enviar leituras CSV da vaga 2: {e}")
                    self.send_error(500, "Erro ao enviar arquivo")
            else:
                self.send_error(404, "Arquivo de leituras da vaga 2 não encontrado")
            return
        elif path == '/download/led':
            if os.path.exists(ARQUIVO_ACOES_LED):
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', 'attachment; filename="acoes_led.csv"')
                    self.end_headers()
                    with open(ARQUIVO_ACOES_LED, 'rb') as f:
                        self.wfile.write(f.read())
                except Exception as e:
                    print(f"Erro ao enviar ações LED CSV: {e}")
                    self.send_error(500, "Erro ao enviar arquivo")
            else:
                self.send_error(404, "Arquivo de ações do LED não encontrado")
            return
        elif path == '/download/eventos':
            if os.path.exists(ARQUIVO_EVENTOS):
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', 'attachment; filename="historico_completo.csv"')
                    self.end_headers()
                    with open(ARQUIVO_EVENTOS, 'rb') as f:
                        self.wfile.write(f.read())
                except Exception as e:
                    print(f"Erro ao enviar eventos CSV: {e}")
                    self.send_error(500, "Erro ao enviar arquivo")
            else:
                self.send_error(404, "Arquivo de histórico consolidado não encontrado")
            return
        elif path == '/download/unificado':
            if os.path.exists(ARQUIVO_UNIFICADO):
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv')
                    self.send_header('Content-Disposition', 'attachment; filename="historico_unificado.csv"')
                    self.end_headers()
                    with open(ARQUIVO_UNIFICADO, 'rb') as f:
                        self.wfile.write(f.read())
                except Exception as e:
                    print(f"Erro ao enviar unificado CSV: {e}")
                    self.send_error(500, "Erro ao enviar arquivo")
            else:
                self.send_error(404, "Arquivo unificado não encontrado")
            return
        
        else:
            self.send_error(404)
            return

# Função para leitura contínua do sensor
def ler_sensor():
    global leituras_historico
    
    while True:
        try:
            # Obter leitura do sensor
            distancia = sensor.medir_distancia()
                
            # Formatar timestamp
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            timestamp_display = datetime.now().strftime('%H:%M:%S')
            
            # Adicionar ao histórico em memória
            leituras_historico.append({'timestamp': timestamp_display, 'valor': distancia})
            
            # Limitar tamanho do histórico em memória
            if len(leituras_historico) > MAX_HISTORICO:
                leituras_historico.pop(0)
            
            # Registrar no arquivo CSV
            registrar_leitura(distancia, timestamp)
                
            time.sleep(intervalo_leitura)
        except Exception as e:
            print(f"Erro na leitura do sensor: {e}")
            time.sleep(intervalo_leitura)

# Função para iniciar o servidor HTTP
def iniciar_servidor():
    handler = SensorHTTPHandler
    
    # Inicializa os arquivos CSV
    inicializar_arquivos_csv()
    
    # Inicia thread para leitura contínua do sensor
    thread_sensor = threading.Thread(target=ler_sensor, daemon=True)
    thread_sensor.start()

    # Inicia thread do loop de estacionamento (duas vagas)
    thread_parking = threading.Thread(target=loop_estacionamento, daemon=True)
    thread_parking.start()
    
    # Configura o servidor para aceitar conexões de qualquer endereço IP
    with socketserver.TCPServer(("0.0.0.0", PORT), handler) as httpd:
        print(f"Servidor iniciado na porta {PORT}")
        print(f"Acesse http://localhost:{PORT} ou http://<IP-DA-RASPBERRY>:{PORT} no navegador")
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        
        httpd.server_close()
        print("Servidor encerrado")

# Função principal
if _name_ == "_main_":
    try:
        # Suporte a argumento de linha de comando para porta
        parser = argparse.ArgumentParser(description="Servidor Lite do monitor de estacionamento")
        parser.add_argument("--port", type=int, default=PORT, help="Porta do servidor HTTP (default: %(default)s)")
        args = parser.parse_args()
        PORT = args.port

        # Inicia o servidor
        print("Iniciando servidor web simplificado...")
        print("VERSÃO LITE: Otimizada para menor consumo de recursos")
        iniciar_servidor()
    except KeyboardInterrupt:
        print("\nEncerrando o programa...")
    finally:
        # Limpa os recursos
        sensor.cleanup()
        print("Sensor limpo e programa encerrado.")