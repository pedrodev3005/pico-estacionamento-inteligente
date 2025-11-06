import http.server
import socketserver
import json
import threading
import time
import random
import os
import csv
from datetime import datetime
from urllib.parse import parse_qs, urlparse

# Variável global para controle do LED
led_status = False

# Simulação do sensor HC-SR04
class SensorSimulado:
    def __init__(self):
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
        def __init__(self, trigger_pin=23, echo_pin=24):
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

# Variáveis globais
leituras_historico = []
MAX_HISTORICO = 20  # Reduzido para economizar memória
intervalo_leitura = 2.0  # Aumentado para reduzir carga no sistema

# Configuração para armazenamento em CSV
DIRETORIO_DADOS = "dados_sensor"
ARQUIVO_LEITURAS = os.path.join(DIRETORIO_DADOS, "leituras_sensor.csv")
ARQUIVO_ACOES_LED = os.path.join(DIRETORIO_DADOS, "acoes_led.csv")
ARQUIVO_EVENTOS = os.path.join(DIRETORIO_DADOS, "historico_completo.csv")

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

# HTML da página principal - Versão simplificada
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Monitoramento Sensor HC-SR04 (Lite)</title>
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
        .reading {
            text-align: center;
            margin: 30px 0;
        }
        .value {
            font-size: 48px;
            font-weight: bold;
            color: #2196F3;
        }
        .timestamp {
            color: #757575;
            margin-top: 5px;
        }
        .controls {
            margin: 20px 0;
            text-align: center;
        }
        button {
            background-color: #2196F3;
            color: white;
            border: none;
            padding: 10px 15px;
            border-radius: 4px;
            cursor: pointer;
            margin: 0 5px;
        }
        button:hover {
            background-color: #0b7dda;
        }
        .led-on {
            background-color: #4CAF50 !important;
        }
        .led-off {
            background-color: #f44336 !important;
        }
        .status {
            text-align: center;
            margin-top: 20px;
            padding: 10px;
            border-radius: 4px;
        }
        .online {
            background-color: #e8f5e9;
            color: #388e3c;
        }
        .offline {
            background-color: #ffebee;
            color: #d32f2f;
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
</head>
<body>
    <div class="container">
        <h1>Monitoramento do Sensor HC-SR04 (Versão Lite)</h1>
        
        <div class="reading">
            <div class="value" id="current-distance">--</div>
            <div class="timestamp" id="reading-time">--:--:--</div>
        </div>
        
        <div class="controls">
            <button id="refresh-btn">Atualizar Leitura</button>
            <button id="led-btn" class="led-off">LED: Desligado</button>
        </div>
        
        <div class="status online" id="status">
            Conectado
        </div>
        
        <div class="historico">
            <h2>Histórico de Leituras</h2>
            <table>
                <thead>
                    <tr>
                        <th>Horário</th>
                        <th>Distância (cm)</th>
                    </tr>
                </thead>
                <tbody id="historico-leituras">
                    <tr><td colspan="2">Carregando dados...</td></tr>
                </tbody>
            </table>
        </div>
        
        <div class="historico">
            <h2>Histórico de Acionamentos do LED</h2>
            <table>
                <thead>
                    <tr>
                        <th>Data/Hora</th>
                        <th>Ação</th>
                        <th>Estado</th>
                    </tr>
                </thead>
                <tbody id="historico-led">
                    <tr><td colspan="3">Carregando dados...</td></tr>
                </tbody>
            </table>
        </div>
        
        <footer>
            Sistema de Monitoramento do Sensor HC-SR04 - Raspberry Pi 3B (Versão Lite)
        </footer>
        
        <div class="historico">
            <h2>Downloads</h2>
            <div class="controls" style="margin-top:10px;">
                <a href="/download/leituras" style="display:inline-block;background-color:#2196F3;color:white;text-decoration:none;padding:10px 15px;border-radius:4px;margin:0 5px;">Baixar Leituras (CSV)</a>
                <a href="/download/led" style="display:inline-block;background-color:#2196F3;color:white;text-decoration:none;padding:10px 15px;border-radius:4px;margin:0 5px;">Baixar Ações do LED (CSV)</a>
                <a href="/download/eventos" style="display:inline-block;background-color:#2196F3;color:white;text-decoration:none;padding:10px 15px;border-radius:4px;margin:0 5px;">Baixar Histórico Consolidado (CSV)</a>
            </div>
        </div>
    </div>

    <script>
        // Elementos da interface
        const currentDistance = document.getElementById('current-distance');
        const readingTime = document.getElementById('reading-time');
        const refreshBtn = document.getElementById('refresh-btn');
        const status = document.getElementById('status');
        const historicoLeituras = document.getElementById('historico-leituras');
        const historicoLed = document.getElementById('historico-led');
        
        // Atualiza a leitura atual
        function updateReading() {
            status.className = 'status online';
            status.textContent = 'Atualizando...';
            
            fetch('/api/leitura')
                .then(response => response.json())
                .then(data => {
                    currentDistance.textContent = data.valor.toFixed(2) + ' cm';
                    readingTime.textContent = data.timestamp;
                    
                    status.className = 'status online';
                    status.textContent = 'Leitura atualizada com sucesso';
                    
                    // Atualiza o histórico após cada leitura
                    atualizarHistorico();
                })
                .catch(error => {
                    console.error('Erro ao buscar dados:', error);
                    status.className = 'status offline';
                    status.textContent = 'Erro ao atualizar leitura';
                });
        }
        
        // Função para atualizar o histórico de leituras
        function atualizarHistorico() {
            fetch('/api/historico')
                .then(response => response.json())
                .then(data => {
                    historicoLeituras.innerHTML = '';
                    
                    if (data.length === 0) {
                        historicoLeituras.innerHTML = '<tr><td colspan="2">Nenhum dado disponível</td></tr>';
                        return;
                    }
                    
                    // Adiciona as últimas leituras na tabela
                    data.forEach(item => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `<td>${item.timestamp}</td><td>${item.valor.toFixed(2)} cm</td>`;
                        historicoLeituras.appendChild(tr);
                    });
                })
                .catch(error => {
                    console.error('Erro ao buscar histórico:', error);
                    historicoLeituras.innerHTML = '<tr><td colspan="2">Erro ao carregar histórico</td></tr>';
                });
        }
        
        // Função para atualizar o histórico de acionamentos do LED
        function atualizarHistoricoLed() {
            fetch('/api/historico/led')
                .then(response => response.json())
                .then(data => {
                    historicoLed.innerHTML = '';
                    
                    if (!Array.isArray(data) || data.length === 0) {
                        historicoLed.innerHTML = '<tr><td colspan="3">Nenhum acionamento registrado</td></tr>';
                        return;
                    }
                    
                    data.forEach(item => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `<td>${item.timestamp}</td><td>${item.acao}</td><td>${item.estado}</td>`;
                        historicoLed.appendChild(tr);
                    });
                })
                .catch(error => {
                    console.error('Erro ao buscar histórico do LED:', error);
                    historicoLed.innerHTML = '<tr><td colspan="3">Erro ao carregar histórico</td></tr>';
                });
        }
        
        // Inicializa a página
        window.addEventListener('load', function() {
            updateReading();
            atualizarHistorico();
            atualizarHistoricoLed();
            
            // Atualiza a cada 5 segundos (reduzido para economizar recursos)
            setInterval(updateReading, 5000);
            setInterval(atualizarHistoricoLed, 10000);
        });
        
        // Botão de atualização manual
        refreshBtn.addEventListener('click', updateReading);
        
        // Controle do LED
        const ledBtn = document.getElementById('led-btn');
        let ledStatus = false;
        
        // Função para alternar o estado do LED
        function toggleLED() {
            fetch('/api/led?estado=' + (ledStatus ? '0' : '1'), {
                method: 'GET'
            })
            .then(response => response.json())
            .then(data => {
                ledStatus = data.estado === 1;
                ledBtn.textContent = 'LED: ' + (ledStatus ? 'Ligado' : 'Desligado');
                ledBtn.className = ledStatus ? 'led-on' : 'led-off';
                
                status.className = 'status online';
                status.textContent = 'LED ' + (ledStatus ? 'ligado' : 'desligado') + ' com sucesso';
                
                // Atualiza histórico de LED após alteração
                setTimeout(atualizarHistoricoLed, 500);
            })
            .catch(error => {
                console.error('Erro ao controlar LED:', error);
                status.className = 'status offline';
                status.textContent = 'Erro ao controlar LED';
            });
        }
        
        // Adiciona evento ao botão do LED
        ledBtn.addEventListener('click', toggleLED);
    </script>
</body>
</html>
"""

# Classe para o servidor HTTP
class SensorHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
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
        
        elif path == '/api/led':
            global led_status
            
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
    PORT = 8001
    handler = SensorHTTPHandler
    
    # Inicializa os arquivos CSV
    inicializar_arquivos_csv()
    
    # Inicia thread para leitura contínua do sensor
    thread_sensor = threading.Thread(target=ler_sensor, daemon=True)
    thread_sensor.start()
    
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


def start_web_server():
    print("Iniciando servidor web simplificado...")
    print("VERSÃO LITE: Otimizada para menor consumo de recursos")
    iniciar_servidor()

if __name__ == "__main__":
    try:
        # Inicia o servidor
        print("Iniciando servidor web simplificado...")
        print("VERSÃO LITE: Otimizada para menor consumo de recursos")
        start_web_server()
    except KeyboardInterrupt:
        print("\nEncerrando o programa...")
    finally:
        # Limpa os recursos
        sensor.cleanup()
        print("Sensor limpo e programa encerrado.")