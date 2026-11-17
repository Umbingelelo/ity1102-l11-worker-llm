import httpx
import openai
import pytest

from app import llm, worker
from conftest import CLAVE, VALIDA


def error_http(codigo):
    respuesta = httpx.Response(codigo, request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1"))
    return openai.APIStatusError(f"HTTP {codigo}", response=respuesta, body=None)


class NvidiaFalso:
    """Responde como cliente.chat.completions.create: primero los errores de la lista, después texto."""

    def __init__(self, errores=(), texto="Resumen para el analista."):
        self.errores = list(errores)
        self.texto = texto
        self.llamadas = 0
        self.chat = self
        self.completions = self

    def create(self, **_):
        self.llamadas += 1
        if self.errores:
            raise self.errores.pop(0)
        mensaje = type("M", (), {"content": self.texto})
        return type("R", (), {"choices": [type("C", (), {"message": mensaje})]})


@pytest.fixture
def esperas():
    return []


# Prueba obligatoria 6, mitad worker: NVIDIA con 429 sostenido
def test_llm_con_429_la_prediccion_queda_y_el_estado_es_degradado(sistema, monkeypatch, esperas):
    falso = NvidiaFalso(errores=[error_http(429)] * llm.INTENTOS)
    monkeypatch.setattr(llm, "cliente", falso)
    r = sistema["cliente"].post("/api/predict", json={**VALIDA, "texto": "¿por qué?"}, headers=CLAVE)
    assert r.status_code == 200
    pedido = sistema["encolados"][0]
    estado = worker.procesar(pedido, sistema["almacen"],
                             redactar=lambda i, c: llm.redactar(i, c, dormir=esperas.append))
    assert estado == "degradado"
    assert falso.llamadas == llm.INTENTOS
    guardada = sistema["cliente"].get(f"/api/predicciones/{pedido['id']}", headers=CLAVE).json()
    assert guardada["estado_llm"] == "degradado" and guardada["probabilidad"] == 0.87
    assert sistema["cliente"].get("/api/health").json()["piezas"]["llm"].startswith("degradado")


def test_reintenta_con_espera_creciente_y_luego_responde(monkeypatch, esperas):
    monkeypatch.setattr(llm, "cliente", NvidiaFalso(errores=[error_http(429), error_http(503)]))
    assert llm.redactar("instrucción", "contenido", dormir=esperas.append) == "Resumen para el analista."
    assert len(esperas) == 2 and esperas[1] > esperas[0] * 1.3


def test_clave_invalida_no_se_reintenta(monkeypatch, esperas):
    falso = NvidiaFalso(errores=[error_http(401)])
    monkeypatch.setattr(llm, "cliente", falso)
    with pytest.raises(llm.LLMNoDisponible, match="401"):
        llm.redactar("instrucción", "contenido", dormir=esperas.append)
    assert falso.llamadas == 1 and esperas == []


def test_worker_no_repite_una_llamada_ya_hecha(sistema):
    sistema["almacen"].hset("prediccion:abc", mapping={"estado_llm": "listo"})
    def no_deberia_llamarse(*_):
        raise AssertionError("llamó al LLM otra vez")
    pedido = {"id": "abc", "caso": "fraude", "prediccion": {}, "texto": ""}
    assert worker.procesar(pedido, sistema["almacen"], redactar=no_deberia_llamarse) == "listo"
