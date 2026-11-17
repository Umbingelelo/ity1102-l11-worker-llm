from app import main
from conftest import CLAVE, VALIDA


# Prueba obligatoria 1
def test_prediccion_valida_responde_200_con_version_de_modelo(sistema):
    r = sistema["cliente"].post("/api/predict", json=VALIDA, headers=CLAVE)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["probabilidad"] == 0.87
    assert cuerpo["decision"] == "revisar"
    assert cuerpo["version_modelo"] == "l10-fraude-20261110"
    # las columnas llegan a SageMaker en el orden del entrenamiento
    assert sistema["sagemaker"].filas == ["250000.0,3.0,4.0,12.0,0.0,3.0,1.0,1.0"]


# Prueba obligatoria 2
def test_campo_faltante_o_de_tipo_incorrecto_responde_422(sistema):
    incompleta = {k: v for k, v in VALIDA.items() if k != "hora"}
    r = sistema["cliente"].post("/api/predict", json=incompleta, headers=CLAVE)
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "hora"]
    r = sistema["cliente"].post("/api/predict", json={**VALIDA, "monto_clp": "mucho"}, headers=CLAVE)
    assert r.status_code == 422
    assert sistema["sagemaker"].filas == []   # una entrada mala nunca llega a SageMaker


# Prueba obligatoria 3
def test_sin_clave_o_con_clave_incorrecta_responde_401(sistema):
    assert sistema["cliente"].post("/api/predict", json=VALIDA).status_code == 401
    r = sistema["cliente"].post("/api/predict", json=VALIDA, headers={"X-API-Key": "otra"})
    assert r.status_code == 401


# Prueba obligatoria 4
def test_rafaga_sobre_el_limite_responde_429(sistema):
    codigos = [sistema["cliente"].post("/api/predict", json=VALIDA, headers=CLAVE).status_code
               for _ in range(main.LIMITE_POR_MINUTO + 1)]
    assert codigos[:-1] == [200] * main.LIMITE_POR_MINUTO
    assert codigos[-1] == 429


# Prueba obligatoria 6, mitad API: la cola caída no tumba la predicción
def test_cola_caida_la_prediccion_responde_igual_en_modo_degradado(sistema, monkeypatch):
    def cola_caida(_pedido):
        raise ConnectionError("RabbitMQ no responde")
    monkeypatch.setattr(main, "publicar", cola_caida)
    r = sistema["cliente"].post("/api/predict", json={**VALIDA, "texto": "¿por qué?"}, headers=CLAVE)
    assert r.status_code == 200
    assert r.json()["estado_llm"] == "degradado"
    guardada = sistema["cliente"].get(f"/api/predicciones/{r.json()['id']}", headers=CLAVE).json()
    assert guardada["probabilidad"] == 0.87


def test_el_texto_llega_anonimizado_a_la_cola_y_a_la_base(sistema):
    texto = "Soy Ana, RUT 12.345.678-9, correo ana@correo.cl"
    r = sistema["cliente"].post("/api/predict", json={**VALIDA, "texto": texto}, headers=CLAVE)
    pedido = sistema["encolados"][0]
    assert "12.345.678-9" not in pedido["texto"] and "ana@correo.cl" not in pedido["texto"]
    assert "12.345.678-9" not in sistema["almacen"].hget(f"prediccion:{r.json()['id']}", "texto")


def test_prediccion_inexistente_responde_404(sistema):
    assert sistema["cliente"].get("/api/predicciones/no-existe", headers=CLAVE).status_code == 404


def test_campo_desconocido_responde_422(sistema):
    r = sistema["cliente"].post("/api/predict", json={**VALIDA, "es_fraude": 1}, headers=CLAVE)
    assert r.status_code == 422


def test_sin_texto_no_se_encola_nada_para_el_llm(sistema):
    r = sistema["cliente"].post("/api/predict", json=VALIDA, headers=CLAVE)
    assert r.json()["estado_llm"] == "no_solicitado"
    assert sistema["encolados"] == []
