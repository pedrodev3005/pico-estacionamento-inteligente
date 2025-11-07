#!/usr/bin/env python3

import subprocess
import time
import board
import busio
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306
import RPi.GPIO as GPIO
import psutil
from enum import Enum, auto


# --- Configurações ---
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64
CARROSSEL_INTERVAL = 3  # Segundos por página do carrossel
MENU_REDRAW_SLEEP = 0.1 # 100ms de pausa no menu
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_SIZE = 9

# Pinos GPIO (BCM numbering)
PIN_CIMA = 17
PIN_BAIXO = 27
PIN_ENTER = 22

# Debounce time para botões (em segundos)
DEBOUNCE_TIME = 0.05

# Conjunto de caracteres para senha
CHARSET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !@#$%^&*()_+-=[]{}|;':\",./<>?"
CHARSET_LEN = len(CHARSET)

# --- Splash / Identidade do Projeto ---
PROJECT_NAME = "Estacionamento Inteligente"
PROJECT_AUTHORS = "Pedro Augusto & Nicholas"
SPLASH_SECONDS = 2.5  # tempo que a tela fica visível


# --- Estados do Programa ---
class EstadoPrograma(Enum):
    CARROSSEL = auto()
    MENU_REDE = auto()
    SENHA = auto()
    CONECTANDO = auto()
    CONECTADO_MSG = auto()
    FALHA_CONEXAO_MSG = auto()

# --- Funções Auxiliares ---
def run_command(command):
    """Executa um comando shell e retorna a saída como string limpa ou None."""
    try:
        result = subprocess.check_output(command, shell=True, text=True, stderr=subprocess.DEVNULL)
        return result.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

# --- Funções de Dados (Tradução das funções C) ---

def is_wifi_connected():
    """Verifica se o Wi-Fi está conectado."""
    ssid = run_command("iwgetid -r")
    return ssid is not None and ssid != ""

def get_wifi_signal():
    """Obtém o nível do sinal Wi-Fi."""
    output = run_command("iwconfig wlan0 | grep 'Signal level'")
    if output:
        try:
            signal = output.split("Signal level=")[1].split(" dBm")[0]
            return f"Sinal: {signal} dBm"
        except IndexError: pass
    output_proc = run_command("cat /proc/net/wireless | tail -n 1 | awk '{print $3}' | sed 's/\\.//'")
    if output_proc: return f"Sinal: ~{output_proc}%"
    return "Sinal: N/A"

def get_ssh_status():
    """Verifica o estado do serviço SSH."""
    result = subprocess.run("systemctl is-active ssh", shell=True, capture_output=True, text=True, check=False)
    return "ATIVO" if result.returncode == 0 else "INATIVO"

def get_ip_address():
    """Obtém o endereço IP da Raspberry."""
    ip = run_command("hostname -I | awk '{print $1}'")
    return ip if ip else "N/A"

def get_network_name():
    """Obtém o nome da rede conectada."""
    ssid = run_command("iwgetid -r")
    return ssid if ssid else "N/A"

def get_hostname():
    """Obtém o hostname."""
    hostname = run_command("hostname")
    return hostname if hostname else "N/A"

def get_num_ssh():
    """Obtém o número de utilizadores SSH."""
    count_str = run_command("who | grep pts | wc -l")
    try: return int(count_str) if count_str else 0
    except ValueError: return 0

def get_ssids():
    """Obtém a lista de SSIDs disponíveis usando nmcli."""
    # Garante que a interface esteja UP antes de listar
    subprocess.run("sudo ip link set wlan0 up", shell=True, capture_output=True)
    time.sleep(0.5) # Pequena pausa para a interface estabilizar

    output = run_command("nmcli -t -f SSID device wifi list")
    if output:
        ssids = sorted([line for line in output.split('\n') if line and line != "--"])
        return ssids if ssids else ["Nenhuma rede"]
    else: return ["Erro ao escanear"]



def connect_to_wifi(ssid, password):
    """Tenta conectar a uma rede Wi-Fi usando nmcli (o script DEVE rodar com sudo)."""
    # Escaping ainda pode ser útil
    ssid_escaped = ssid.replace('"', '\\"')
    password_escaped = password.replace('"', '\\"')
    # REMOVIDO o 'sudo' daqui
    command = f'nmcli device wifi connect "{ssid_escaped}" password "{password_escaped}"'
    print(f"\n[DEBUG] Tentando conectar a: {ssid}")
    print(f"[DEBUG] Executando (sem sudo interno): {command}")
    try:
        # Mantendo shell=True por causa das aspas complexas, mas adiciona timeout
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True, timeout=30) # Timeout de 30 segundos

        print(f"[DEBUG] Conexão bem-sucedida! Saída: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[DEBUG] Falha na conexão (código: {e.returncode})")
        # Verifica ambos stdout e stderr para a mensagem de erro
        error_msg = e.stderr.strip() if e.stderr else ""
        if not error_msg and e.stdout: # Se stderr vazio, usa stdout
            error_msg = e.stdout.strip()
        print(f"[DEBUG] Erro nmcli: {error_msg}")
        return False
    except subprocess.TimeoutExpired:
        print("[DEBUG] Erro: Comando nmcli demorou muito para responder.")
        return False
    except FileNotFoundError:
        print("[DEBUG] Erro: Comando 'nmcli' não encontrado.")
        return False
    except Exception as e: # Captura outros erros inesperados
         print(f"[DEBUG] Erro inesperado ao tentar conectar: {e}")
         return False

# --- Funções de Display ---
def setup_display():
    """Configura e inicializa o display OLED."""
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        disp = adafruit_ssd1306.SSD1306_I2C(DISPLAY_WIDTH, DISPLAY_HEIGHT, i2c)
        disp.fill(0)
        disp.show()
        image = Image.new("1", (disp.width, disp.height))
        draw = ImageDraw.Draw(image)
        try:
             font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        except IOError:
             print(f"Aviso: Fonte {FONT_PATH} não encontrada, usando fonte padrão.")
             font = ImageFont.load_default()
        return disp, image, draw, font
    except Exception as e:
        print(f"Erro Crítico: Display I2C: {e}")
        sys.exit(1)

def display_clear(draw, disp, image):
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)

def display_text(draw, font, text, x, y, wrap=False, max_width=DISPLAY_WIDTH):
    """Desenha texto no buffer, com quebra de linha opcional."""
    if wrap:
        lines = []
        words = text.split(' ')
        current_line = ""
        for word in words:
            # Verifica se a palavra cabe na linha atual
            test_line = f"{current_line} {word}".strip()
            bbox = font.getbbox(test_line)
            text_width = bbox[2] - bbox[0] # Largura calculada
            if text_width <= max_width:
                current_line = test_line
            else:
                # Palavra não cabe, começa nova linha
                lines.append(current_line)
                current_line = word
                bbox_word = font.getbbox(word)
                if bbox_word[2] - bbox_word[0] > max_width: # Palavra maior que a linha
                     # Truncar palavra (poderia implementar quebra no meio)
                     # Por agora, apenas truncamos
                     while font.getbbox(current_line)[2] - font.getbbox(current_line)[0] > max_width:
                          current_line = current_line[:-1]
                     current_line += "..."


        lines.append(current_line) # Adiciona a última linha

        # Desenha as linhas
        line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + 2 # Altura aproximada
        for i, line in enumerate(lines):
            draw.text((x, y + i * line_height), line, font=font, fill=255)
    else:
        # Desenho simples sem quebra
        draw.text((x, y), text, font=font, fill=255)


def draw_centered_text(draw, font, text, y, disp_width=DISPLAY_WIDTH):
    """Desenha uma linha de texto centralizada no eixo X."""
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0]
    x = max(0, (disp_width - w) // 2)
    draw.text((x, y), text, font=font, fill=255)

def show_splash(disp, image, draw, font):
    """Exibe a tela de abertura com nome do projeto e autores."""
    display_clear(draw, disp, image)
    # título (maior). tenta uma fonte maior, caindo pra atual se faltar
    try:
        font_big = ImageFont.truetype(FONT_PATH, FONT_SIZE + 5)
    except Exception:
        font_big = font
    # distribui as linhas verticalmente
    y0 = 10
    draw_centered_text(draw, font_big, PROJECT_NAME, y0)
    draw_centered_text(draw, font, "by", y0 + 18)
    draw_centered_text(draw, font, PROJECT_AUTHORS, y0 + 30)
    display_show(disp, image)
    time.sleep(SPLASH_SECONDS)
    display_clear(draw, disp, image)
    display_show(disp, image)




def display_show(disp, image):
    """Envia o buffer para o display."""
    disp.image(image)
    disp.show()

# --- Funções de GPIO ---
def setup_gpio():
    """Configura os pinos GPIO para os botões."""
    GPIO.setwarnings(False) # Desativa avisos de pinos já em uso
    GPIO.setmode(GPIO.BCM) # Usa numeração BCM
    # Configura pinos como entrada com pull-down interno
    GPIO.setup(PIN_CIMA, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(PIN_BAIXO, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    GPIO.setup(PIN_ENTER, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

def read_button_debounced(pin, button_states):
    """Lê um botão com debounce simples baseado em tempo."""
    current_state = GPIO.input(pin)
    now = time.monotonic()
    pressed = False

    # Acessa estado anterior e info de debounce
    last_state, last_time, debounce_info = button_states.get(pin, (GPIO.LOW, now, {'debounced': False})) # Usa .get para segurança

    if current_state != last_state:
        # Estado mudou, reinicia timer e estado debounced
        button_states[pin] = (current_state, now, {'debounced': False})
    elif current_state == GPIO.HIGH: # Estado está ALTO (pressionado)
        # Verifica se tempo suficiente passou E se já não foi registado
        if now - last_time > DEBOUNCE_TIME and not debounce_info.get('debounced', False):
            pressed = True
            # Marca que já registou este pressionar
            button_states[pin] = (current_state, last_time, {'debounced': True}) # Mantém last_time original do início do press
    elif current_state == GPIO.LOW:
         # Botão solto, reseta a flag 'debounced' se necessário
         if debounce_info.get('debounced', True): # Reseta se estava True ou se nunca foi definido
              button_states[pin] = (current_state, now, {'debounced': False}) # Atualiza last_time para o momento do release

    return pressed

# --- MAIN ---
def main():

    disp, image, draw, font = setup_display()
    setup_gpio()

    # Tela inicial do projeto (splash)
    show_splash(disp, image, draw, font)

    # Estado inicial dos botões para debounce
    button_states = {
        PIN_CIMA: (GPIO.LOW, time.monotonic(), {'debounced': False}),
        PIN_BAIXO: (GPIO.LOW, time.monotonic(), {'debounced': False}),
        PIN_ENTER: (GPIO.LOW, time.monotonic(), {'debounced': False}),
    }

    # --- Variáveis de Estado ---
    estado = EstadoPrograma.CARROSSEL
    pagina_carrossel = 0
    item_menu_rede = 0
    num_redes = 0
    redes_encontradas = []
    redes_escaneadas = False
    ssid_selecionado = ""
    senha_digitada = ""
    senha_index = 0 # Não usado diretamente, usamos len(senha_digitada)
    char_atual_index = 0
    oled_clear_needed = True # Flag para limpar o display

    last_display_update = 0


    processo_conexao = None
    ssid_tentando = ""
    senha_tentando = ""


    print("Programa iniciado. Use os botões. Pressione ENTER no menu principal para sair.")

    while True:
        # --- 1. Ler Botões ---
        cima_pressed = read_button_debounced(PIN_CIMA, button_states)
        baixo_pressed = read_button_debounced(PIN_BAIXO, button_states)
        enter_pressed = read_button_debounced(PIN_ENTER, button_states)

        # --- 2. Lógica Principal de Estados ---
        current_time = time.time()
        needs_redraw_this_iteration = False

        # Verifica conexão e define o estado base
        wifi_ok = is_wifi_connected()

        # ====================================================================
        #                      ESTADO: WI-FI CONECTADO (CARROSSEL)
        # ====================================================================
        if wifi_ok and estado not in [EstadoPrograma.CONECTANDO, EstadoPrograma.CONECTADO_MSG]:
            if estado != EstadoPrograma.CARROSSEL:
                estado = EstadoPrograma.CARROSSEL
                redes_escaneadas = False
                last_display_update = 0
                needs_redraw_this_iteration = True

            if needs_redraw_this_iteration or (current_time - last_display_update >= CARROSSEL_INTERVAL):
                last_display_update = current_time
                display_clear(draw, disp, image)

                # Coleta e formata dados
                network_name = get_network_name()
                hostname = get_hostname()
                num_ssh = get_num_ssh()
                wifi_signal = get_wifi_signal()
                ssh_status = get_ssh_status()
                ip_address = get_ip_address()
                WEB_PORT = 8001

                line_rede = f"Rede: {network_name}"
                line_host = f"Host: {hostname}"
                line_ip = f"IP: {ip_address}:{WEB_PORT}" if ip_address != "N/A" else "IP: N/A"
                line_ssh_status = f"SSH: {ssh_status}"
                line_ssh_users = f"Users: {num_ssh}"

                display_text(draw, font, "Status: CONECTADO", 0, 0)
                if pagina_carrossel == 0:
                    display_text(draw, font, line_rede, 0, 15)
                    display_text(draw, font, line_host, 0, 30)
                    display_text(draw, font, line_ip, 0, 45)
                else:
                    display_text(draw, font, wifi_signal, 0, 15)
                    display_text(draw, font, line_ssh_status, 0, 30)
                    display_text(draw, font, line_ssh_users, 0, 45)

                pagina_carrossel = (pagina_carrossel + 1) % 2
                display_show(disp, image)
                needs_redraw_this_iteration = False # Acabámos de redesenhar

        # ====================================================================
        #                  ESTADO: WI-FI DESCONECTADO (MENU/SENHA/MENSAGENS)
        # ====================================================================
        # Bloco "rede/senha/conectar/mensagens temporárias"
        # Bloco "rede/senha/conectar/mensagens temporárias"
        elif (not wifi_ok) or (estado in [
                EstadoPrograma.CONECTANDO,
                EstadoPrograma.CONECTADO_MSG,
                EstadoPrograma.FALHA_CONEXAO_MSG
            ]):

            # Gerencia transição e scan
            if estado == EstadoPrograma.CARROSSEL:
                estado = EstadoPrograma.MENU_REDE
                item_menu_rede = 0
                num_redes = 0
                redes_escaneadas = False
                needs_redraw_this_iteration = True
                oled_clear_needed = True

            if not redes_escaneadas and estado == EstadoPrograma.MENU_REDE:
                 if oled_clear_needed: display_clear(draw, disp, image); oled_clear_needed = False
                 display_text(draw, font, "A escanear...", 0, 20)
                 display_show(disp, image)

                 redes_encontradas = get_ssids() # Recebe a lista
                 num_redes = len(redes_encontradas) if redes_encontradas[0] not in ["Erro ao escanear", "Nenhuma rede"] else 0
                 redes_escaneadas = True
                 oled_clear_needed = True # Força limpeza para desenhar o menu
                 needs_redraw_this_iteration = True # Força redesenho do menu

            # --- Processar Input dos Botões ---
            action_taken = False
            if estado == EstadoPrograma.MENU_REDE:
                if cima_pressed and num_redes > 0:
                    item_menu_rede = (item_menu_rede - 1 + num_redes) % num_redes
                    oled_clear_needed = True; action_taken = True
                elif baixo_pressed and num_redes > 0:
                    item_menu_rede = (item_menu_rede + 1) % num_redes
                    oled_clear_needed = True; action_taken = True
                elif enter_pressed:
                    if num_redes > 0:
                        estado = EstadoPrograma.SENHA
                        ssid_selecionado = redes_encontradas[item_menu_rede]
                        senha_digitada = ""
                        char_atual_index = 0
                    else:
                        # Se não há redes, ENTER re-escaneia
                        redes_escaneadas = False
                    oled_clear_needed = True; action_taken = True

            elif estado == EstadoPrograma.SENHA:
                action_taken_senha = False # Flag local para saber se CIMA/BAIXO foi pressionado

                if cima_pressed:
                    char_atual_index = (char_atual_index + 1) % CHARSET_LEN
                    oled_clear_needed = True; action_taken = True
                    action_taken_senha = True # Marca que CIMA foi pressionado
                elif baixo_pressed:
                    char_atual_index = (char_atual_index - 1 + CHARSET_LEN) % CHARSET_LEN
                    oled_clear_needed = True; action_taken = True
                    action_taken_senha = True # Marca que BAIXO foi pressionado
                elif enter_pressed:
                    char_selecionado = CHARSET[char_atual_index]
                    # Adiciona caractere ou finaliza
                    if char_selecionado == '*': # Finaliza a senha
                         if len(senha_digitada) > 0:
                                estado = EstadoPrograma.CONECTANDO
                                oled_clear_needed = True
                                action_taken = True

                                # salva os dados que vamos tentar
                                ssid_tentando = ssid_selecionado
                                senha_tentando = senha_digitada

                                # inicia o processo de conexão ASSÍNCRONO
                                ssid_escaped = ssid_tentando.replace('"', '\\"')
                                password_escaped = senha_tentando.replace('"', '\\"')
                                command = f'nmcli device wifi connect "{ssid_escaped}" password "{password_escaped}"'

                                print(f"[DEBUG] Iniciando conexão async: {command}")
                                processo_conexao = subprocess.Popen(
                                    command,
                                    shell=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True
                                )
                                # limpa a senha atual da caixa de digitação pra não reaparecer depois se falhar
                                senha_digitada = ""
                                char_atual_index = 0

                    # Backspace (exemplo com '<')
                    elif char_selecionado == '<':
                         if len(senha_digitada) > 0:
                              senha_digitada = senha_digitada[:-1]
                              char_atual_index = 0 # Reseta caractere
                              oled_clear_needed = True; action_taken = True
                    # Adiciona caractere normal
                    elif len(senha_digitada) < 63:
                        senha_digitada += char_selecionado
                        char_atual_index = 0 # Reseta para 'a'
                        oled_clear_needed = True; action_taken = True

                # --- ADICIONA ATRASO APÓS CIMA/BAIXO ---
                if action_taken_senha:
                    time.sleep(0.15) # Pausa de 150ms após CIMA ou BAIXO
                # ----------------------------------------

            # --- Redesenhar Display se Necessário ---
            if needs_redraw_this_iteration or action_taken or oled_clear_needed:
                if oled_clear_needed:
                    display_clear(draw, disp, image)
                    oled_clear_needed = False

                if estado == EstadoPrograma.MENU_REDE:
                    titulo = f"Redes ({num_redes}):"
                    display_text(draw, font, titulo, 0, 0)
                    if num_redes == 0:
                        display_text(draw, font, redes_encontradas[0], 0, 15) # Mostra "Nenhuma rede" ou "Erro"
                        display_text(draw, font, "ENTER p/ scan", 0, 30)
                    else:
                        # Mostra 3 redes por vez, com scroll
                        start_index = (item_menu_rede // 3) * 3
                        for i in range(3):
                            idx = start_index + i
                            if idx < num_redes:
                                prefixo = ">" if idx == item_menu_rede else " "
                                nome_rede = redes_encontradas[idx]
                                # Truncar nome se necessário
                                if font.getbbox(nome_rede)[2] > DISPLAY_WIDTH - 10:
                                     while font.getbbox(nome_rede + "...")[2] > DISPLAY_WIDTH - 10:
                                          nome_rede = nome_rede[:-1]
                                     nome_rede += "..."
                                display_text(draw, font, f"{prefixo} {nome_rede}", 0, 15 + i * 15)

                elif estado == EstadoPrograma.SENHA:
                    titulo = f"Senha: {ssid_selecionado[:18]}" + ("..." if len(ssid_selecionado) > 18 else "")
                    display_text(draw, font, titulo, 0, 0)

                    # Asteriscos + caractere atual
                    display_text(draw, font, "*" * len(senha_digitada) + CHARSET[char_atual_index], 0, 20)

                    display_text(draw, font, "C/B: Muda", 0, 40)
                    display_text(draw, font, "ENT: Add/'*'=OK", 0, 50)
                    # Adicionar indicação de Backspace se implementado

                elif estado == EstadoPrograma.CONECTANDO:
                     display_text(draw, font, "Conectando...", 0, 20)
                     display_text(draw, font, ssid_selecionado, 0, 35)

                elif estado == EstadoPrograma.CONECTADO_MSG:
                     display_text(draw, font, "Conectado!", 0, 30)

                elif estado == EstadoPrograma.FALHA_CONEXAO_MSG:
                     display_text(draw, font, "Falha na conexão!", 0, 20)
                     display_text(draw, font, "Verifique a senha.", 0, 35)


                display_show(disp, image)

            # --- Transições de Estado Pós-Desenho ---

            if estado == EstadoPrograma.CONECTANDO:
                # 1. já estamos conectados? (às vezes o Wi-Fi sobe antes do nmcli encerrar)
                if is_wifi_connected():
                    print("[DEBUG] Wi-Fi já conectado (detecção antecipada)")
                    estado = EstadoPrograma.CONECTADO_MSG
                    last_display_update = time.time()
                    oled_clear_needed = True

                    # Se o processo ainda tá vivo, manda encerrar educadamente
                    if processo_conexao is not None:
                        try:
                            processo_conexao.terminate()
                        except Exception as e:
                            print(f"[DEBUG] erro ao terminar processo_conexao: {e}")
                    processo_conexao = None

                # 2. senão, verifica se o processo nmcli acabou por conta própria
                elif processo_conexao is not None:
                    retorno = processo_conexao.poll()  # None = ainda rodando
                    if retorno is not None:
                        # terminou!
                        stdout_txt, stderr_txt = processo_conexao.communicate()
                        print(f"[DEBUG] nmcli terminou. code={retorno}")
                        print(f"[DEBUG] STDOUT: {stdout_txt.strip()}")
                        print(f"[DEBUG] STDERR: {stderr_txt.strip()}")

                        if retorno == 0:
                            estado = EstadoPrograma.CONECTADO_MSG
                        else:
                            estado = EstadoPrograma.FALHA_CONEXAO_MSG

                        last_display_update = time.time()
                        oled_clear_needed = True
                        processo_conexao = None


            elif estado == EstadoPrograma.CONECTADO_MSG:
                 if time.time() - last_display_update > 2: # Mostra msg por 2 seg
                      estado = EstadoPrograma.CARROSSEL # Volta ao normal
                      oled_clear_needed = True

            elif estado == EstadoPrograma.FALHA_CONEXAO_MSG:
                 if time.time() - last_display_update > 3: # Mostra msg por 3 seg
                      estado = EstadoPrograma.SENHA # Volta para digitar senha
                      senha_digitada = "" # Limpa a senha anterior
                      char_atual_index = 0
                      oled_clear_needed = True


        # --- Pausa Mínima ---
        time.sleep(MENU_REDRAW_SLEEP)

    # --- Limpeza ---
    print("\nLimpando GPIO...")
    GPIO.cleanup()
    print("Limpando display...")
    display_clear(draw, disp, image)
    display_text(draw, font, "Desligando...", 10, 30)
    display_show(disp, image)
    time.sleep(1)
    disp.fill(0) # Garante que o display apaga
    disp.show()
    # disable_raw_mode() será chamado por atexit() se enable_raw_mode foi usado
    print("Programa finalizado.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSaída forçada pelo utilizador.")
        # Garante limpeza mesmo com CTRL+C
        try:
            GPIO.cleanup()
            # Tentar limpar display aqui pode falhar se já fechado
        except:
            pass
        # A função atexit deve restaurar o terminal se necessário