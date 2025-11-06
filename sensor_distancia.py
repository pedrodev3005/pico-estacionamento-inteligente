import RPi.GPIO as GPIO
import time

#===================================Sensor Setup==========================#
# Use BCM pin numbering
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False) # Desativa avisos

# Define os pinos GPIO (BCM)
PIN_TRIGGER = 23 # GPIO 3
PIN_ECHO = 24    # GPIO 2

# Configura os pinos
GPIO.setup(PIN_TRIGGER, GPIO.OUT)
GPIO.setup(PIN_ECHO, GPIO.IN)

#===================================Main Loop============================#
print("A medir distância (Pressione CTRL+C para sair)")

try:
    while True:
        # Garante que o Trigger começa em nível baixo
        GPIO.output(PIN_TRIGGER, GPIO.LOW)
        #print("Aguardando sensor estabilizar...")
        time.sleep(0.2) # Pequena pausa

        # Envia o pulso de trigger (10 microssegundos)
        #print("Enviando pulso de trigger...")
        GPIO.output(PIN_TRIGGER, GPIO.HIGH)
        time.sleep(0.00001) # 10 us
        GPIO.output(PIN_TRIGGER, GPIO.LOW)

        pulse_start_time = time.time()
        pulse_end_time = time.time()

        # Guarda o tempo de início do pulso de echo
        #print("Aguardando início do echo...")
        while GPIO.input(PIN_ECHO) == 0:
            pulse_start_time = time.time()
            # Adiciona timeout para evitar loop infinito
            if pulse_start_time - pulse_end_time > 0.1: # Timeout de 100ms
                 print("Timeout esperando Echo HIGH")
                 pulse_start_time = time.time() # Reseta para evitar cálculo errado
                 break

        # Sai do loop interno se timeout ocorreu
        if GPIO.input(PIN_ECHO) == 0 and pulse_start_time - pulse_end_time > 0.1:
            time.sleep(0.5) # Espera antes de tentar de novo
            continue

        # Guarda o tempo de fim do pulso de echo
        #print("Aguardando fim do echo...")
        while GPIO.input(PIN_ECHO) == 1:
            pulse_end_time = time.time()
            # Adiciona timeout para evitar loop infinito
            if pulse_end_time - pulse_start_time > 0.1: # Timeout de 100ms
                 print("Timeout esperando Echo LOW")
                 pulse_end_time = pulse_start_time # Reseta para evitar cálculo errado
                 break

        # Sai do loop principal se timeout ocorreu
        if GPIO.input(PIN_ECHO) == 1 and pulse_end_time - pulse_start_time > 0.1:
            time.sleep(0.5) # Espera antes de tentar de novo
            continue


        # Calcula a duração do pulso
        pulse_duration = pulse_end_time - pulse_start_time

        # Calcula a distância (velocidade do som ~34300 cm/s)
        # Distância = (Tempo * Velocidade) / 2
        distance = (pulse_duration * 34300) / 2     

        # Printa a distância
        print(f"Distancia: {distance:.2f} cm")

        # Pausa antes da próxima leitura
        time.sleep(0.5)

except KeyboardInterrupt:
    print("Medição interrompida pelo utilizador.")

finally:
    # Limpa a configuração dos pinos GPIO ao sair
    print("Limpando GPIO...")
    GPIO.cleanup()