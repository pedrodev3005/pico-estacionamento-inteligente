import RPi.GPIO as GPIO
import time

# =================================== Configuração ============================ #
# Use BCM pin numbering
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)  # Desativa avisos

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

# Configura pinos dos sensores
GPIO.setup(S1_TRIGGER, GPIO.OUT)
GPIO.setup(S1_ECHO, GPIO.IN)
GPIO.setup(S2_TRIGGER, GPIO.OUT)
GPIO.setup(S2_ECHO, GPIO.IN)

# Configura pinos dos LEDs e buzzers
for pin in [LED_VAGA1_VERMELHO, LED_VAGA1_VERDE, LED_VAGA2_VERMELHO, LED_VAGA2_VERDE,
            BUZZER_VAGA1, BUZZER_VAGA2]:
    try:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    except Exception as e:
        print(f"Aviso: falha ao configurar GPIO {pin}: {e}")


def medir_distancia(trigger_pin, echo_pin):
    """Mede a distância em cm seguindo a mesma lógica-base com timeouts."""
    # Garante que o Trigger começa em nível baixo
    GPIO.output(trigger_pin, GPIO.LOW)
    time.sleep(0.2)  # Pequena pausa

    # Envia o pulso de trigger (10 microssegundos)
    GPIO.output(trigger_pin, GPIO.HIGH)
    time.sleep(0.00001)  # 10 us
    GPIO.output(trigger_pin, GPIO.LOW)

    pulse_start_time = time.time()
    pulse_end_time = time.time()

    # Aguardando início do echo
    while GPIO.input(echo_pin) == 0:
        pulse_start_time = time.time()
        # Timeout para evitar loop infinito
        if pulse_start_time - pulse_end_time > 0.1:  # 100ms
            # Timeout esperando Echo HIGH
            return None  # indica falha de leitura

    # Aguardando fim do echo
    while GPIO.input(echo_pin) == 1:
        pulse_end_time = time.time()
        # Timeout para evitar loop infinito
        if pulse_end_time - pulse_start_time > 0.1:  # 100ms
            # Timeout esperando Echo LOW
            return None  # indica falha de leitura

    # Calcula a duração do pulso
    pulse_duration = pulse_end_time - pulse_start_time

    # Calcula a distância (velocidade do som ~34300 cm/s)
    distance = (pulse_duration * 34300) / 2
    return distance


def atualizar_atuadores(dist_cm, led_vermelho, led_verde, buzzer):
    """Atualiza LED e buzzer de uma vaga a partir da distância medida."""
    def write_output(pin, turn_on, active_high=True):
        if active_high:
            GPIO.output(pin, GPIO.HIGH if turn_on else GPIO.LOW)
        else:
            GPIO.output(pin, GPIO.LOW if turn_on else GPIO.HIGH)

    if dist_cm is None:
        # Falha na leitura: apaga LEDs e buzzer para segurança
        write_output(led_vermelho, False, True)
        write_output(led_verde, False, True)
        write_output(buzzer, False, True)
        return "falha"

    ocupada = dist_cm < THRESHOLD_OCUPADA_CM
    muito_proximo = dist_cm < THRESHOLD_MUITO_PROXIMO_CM

    # LEDs: exclusivo por vaga
    if led_vermelho == LED_VAGA1_VERMELHO and led_verde == LED_VAGA1_VERDE:
        write_output(LED_VAGA1_VERMELHO, ocupada, LED_VAGA1_RED_ACTIVE_HIGH)
        write_output(LED_VAGA1_VERDE, not ocupada, LED_VAGA1_GREEN_ACTIVE_HIGH)
    elif led_vermelho == LED_VAGA2_VERMELHO and led_verde == LED_VAGA2_VERDE:
        write_output(LED_VAGA2_VERMELHO, ocupada, LED_VAGA2_RED_ACTIVE_HIGH)
        write_output(LED_VAGA2_VERDE, not ocupada, LED_VAGA2_GREEN_ACTIVE_HIGH)
    else:
        # fallback genérico
        write_output(led_vermelho, ocupada, True)
        write_output(led_verde, not ocupada, True)

    # Buzzer: emite quando muito próximo
    if buzzer == BUZZER_VAGA1:
        write_output(BUZZER_VAGA1, muito_proximo, BUZZER_VAGA1_ACTIVE_HIGH)
    elif buzzer == BUZZER_VAGA2:
        write_output(BUZZER_VAGA2, muito_proximo, BUZZER_VAGA2_ACTIVE_HIGH)
    else:
        write_output(buzzer, muito_proximo, True)

    return "ocupada" if ocupada else "livre"


# =================================== Loop Principal ========================= #
print("Monitorando duas vagas com sensores ultrassônicos (CTRL+C para sair)")

try:
    while True:
        # Vaga 1
        d1 = medir_distancia(S1_TRIGGER, S1_ECHO)
        estado1 = atualizar_atuadores(d1, LED_VAGA1_VERMELHO, LED_VAGA1_VERDE, BUZZER_VAGA1)

        # Vaga 2
        d2 = medir_distancia(S2_TRIGGER, S2_ECHO)
        estado2 = atualizar_atuadores(d2, LED_VAGA2_VERMELHO, LED_VAGA2_VERDE, BUZZER_VAGA2)

        # Prints informativos
        if d1 is None:
            print("Vaga 1: leitura falhou")
        else:
            print(f"Vaga 1: {d1:.2f} cm -> {estado1}")

        if d2 is None:
            print("Vaga 2: leitura falhou")
        else:
            print(f"Vaga 2: {d2:.2f} cm -> {estado2}")

        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nMedição interrompida pelo usuário.")

finally:
    # Limpa a configuração dos pinos GPIO ao sair
    print("Limpando GPIO...")
    GPIO.cleanup()