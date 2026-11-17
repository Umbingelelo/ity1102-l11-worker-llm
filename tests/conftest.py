"""Las pruebas corren sin AWS, sin RabbitMQ, sin Redis y sin NVIDIA: cada pieza externa se reemplaza
por un doble que responde lo que la prueba necesita. Así corren en el runner de GitHub Actions.
"""
import io
import os

import fakeredis
import pytest

os.environ.update(CASO="fraude", API_KEYS="clave-de-prueba", LIMITE_POR_MINUTO="5", NVIDIA_MODEL="modelo-de-prueba")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

CLAVE = {"X-API-Key": "clave-de-prueba"}
VALIDA = {"monto_clp": 250000, "hora": 3, "intentos_previos_1h": 4, "edad_cuenta_dias": 12,
          "nivel_kyc": 0, "usuarios_distintos": 3, "emulador": 1, "pais_distinto": 1}


class SageMakerFalso:
    """Responde como invoke_endpoint y describe_endpoint, sin salir del computador."""

    def __init__(self, probabilidad=b"0.87"):
        self.probabilidad = probabilidad
        self.filas = []

    def invoke_endpoint(self, EndpointName, ContentType, Body):
        self.filas.append(Body)
        return {"Body": io.BytesIO(self.probabilidad)}

    def describe_endpoint(self, EndpointName):
        return {"EndpointStatus": "InService", "EndpointConfigName": "l10-fraude-20261110"}


@pytest.fixture
def sistema(monkeypatch):
    almacen = fakeredis.FakeRedis(decode_responses=True)
    sm = SageMakerFalso()
    encolados = []
    monkeypatch.setattr(main, "almacen", almacen)
    monkeypatch.setattr(main, "runtime", sm)
    monkeypatch.setattr(main, "sagemaker", sm)
    monkeypatch.setattr(main, "publicar", encolados.append)
    monkeypatch.setattr(main, "_version", None)
    return {"cliente": TestClient(main.app), "almacen": almacen, "sagemaker": sm, "encolados": encolados}
