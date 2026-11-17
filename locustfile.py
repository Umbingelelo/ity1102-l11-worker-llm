"""Prueba de carga de POST /api/predict. Nunca contra el LLM: mediría el límite de NVIDIA, no tu sistema.

    pip install locust==2.47.0
    API_KEY=<tu clave> locust -f locustfile.py --host https://<tu-ip-con-guiones>.sslip.io \
        --headless -u 20 -r 5 -t 3m --csv carga

Ojo con el rate limiting: con 20 usuarios pasas de 60 solicitudes por minuto en segundos y la mayoría
de las respuestas serán 429. Para medir el sistema, usa una clave solo para la prueba y sube
LIMITE_POR_MINUTO en el .env mientras dura. Los 429 que aparezcan igual son tu límite funcionando.
"""
import os

from locust import HttpUser, between, task

ENTRADAS = {
    "rfm": {"recency": 10, "frequency": 30, "monetary": 800},
    "fraude": {"monto_clp": 250000, "hora": 3, "intentos_previos_1h": 4, "edad_cuenta_dias": 12,
               "nivel_kyc": 0, "usuarios_distintos": 3, "emulador": 1, "pais_distinto": 1},
    "chatbot": {"turnos": 18, "intentos_fallidos": 2, "puntaje_molestia": 0.7, "confianza_intencion": 0.35,
                "deuda_vigente": 150000, "antiguedad_meses": 24},
    "recomendacion": {"compras_previas": 5, "ticket_promedio": 120000, "precio_lista": 90000,
                      "categoria_vista": 1, "ventas_30d": 45},
}


class Cliente(HttpUser):
    wait_time = between(0.5, 1.5)

    @task
    def predecir(self):
        self.client.post("/api/predict", json=ENTRADAS[os.getenv("CASO", "fraude")],
                         headers={"X-API-Key": os.environ["API_KEY"]})
