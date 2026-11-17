"""El microservicio de IA de EP3: predice con SageMaker, guarda, y encola el texto del LLM.

La predicción responde sola. El LLM va por la cola y llega después: si NVIDIA se cae, la predicción
no se entera. Credenciales de AWS: ninguna. boto3 las toma del rol de la EC2 (LabInstanceProfile).
"""
import hashlib
import hmac
import json
import os
import time
import uuid

import boto3
import pika
import redis
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import ConfigDict, Field, create_model

from app.anonimizar import anonimizar
from app.casos import CASOS
from app.cola import COLA, COLA_FALLIDOS, conectar, declarar

CASO = os.getenv("CASO", "rfm")
ENDPOINT = os.getenv("ENDPOINT") or f"l10-{CASO}"
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
UMBRAL = float(os.getenv("UMBRAL", "0.5"))
API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
LIMITE_POR_MINUTO = int(os.getenv("LIMITE_POR_MINUTO", "60"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
COLUMNAS = CASOS[CASO]["columnas"]

# Sin reintentos de boto3 y con tiempo máximo: si SageMaker no responde, la API lo dice rápido.
# 10 s de lectura porque el cold start de un endpoint serverless medido en L10 ronda los 6 s.
runtime = boto3.client("sagemaker-runtime", region_name=REGION, config=Config(
    connect_timeout=2, read_timeout=float(os.getenv("SAGEMAKER_TIMEOUT", "10")),
    retries={"total_max_attempts": 1, "mode": "standard"}))
sagemaker = boto3.client("sagemaker", region_name=REGION, config=Config(
    connect_timeout=2, read_timeout=5, retries={"total_max_attempts": 1, "mode": "standard"}))
almacen = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)

Entrada = create_model(
    "Entrada",
    __config__=ConfigDict(extra="forbid", json_schema_extra={"example": {
        **dict(zip(COLUMNAS, CASOS[CASO]["ejemplo"])),
        "texto": "Hola, soy Ana, mi RUT es 12.345.678-9 y mi correo ana@correo.cl",
    }}),
    texto=(str, Field(default="", max_length=2000,
                      description="Texto libre para el LLM. Se anonimiza antes de encolarlo")),
    **{c: (float, ...) for c in COLUMNAS},
)

app = FastAPI(title=f"L11 · microservicio de IA · caso {CASO}",
              description="Predicción síncrona con SageMaker y texto del LLM por la cola.")


def log(**campos):
    # Una línea JSON por evento: en CloudWatch Logs se busca por "id" sin parsear nada.
    print(json.dumps(campos, ensure_ascii=False), flush=True)


def requiere_clave(x_api_key: str | None = Header(default=None)):
    if not x_api_key or not any(hmac.compare_digest(x_api_key, k) for k in API_KEYS):
        raise HTTPException(status_code=401, detail="Falta X-API-Key o no es válida")
    # Rate limiting por clave, con una ventana fija de un minuto guardada en Redis.
    # En Redis no queda la clave, solo un resumen de ella.
    ventana = int(time.time() // 60)
    contador = f"limite:{hashlib.sha256(x_api_key.encode()).hexdigest()[:12]}:{ventana}"
    usadas = almacen.incr(contador)
    if usadas == 1:
        almacen.expire(contador, 60)
    if usadas > LIMITE_POR_MINUTO:
        raise HTTPException(status_code=429, detail=f"Más de {LIMITE_POR_MINUTO} solicitudes por minuto",
                            headers={"Retry-After": str(60 - int(time.time()) % 60)})


_version = None


def version_modelo() -> str:
    """La versión es la configuración del endpoint: cambia cada vez que se publica un modelo nuevo."""
    global _version
    if os.getenv("MODELO_VERSION"):
        return os.environ["MODELO_VERSION"]
    if _version is None:
        try:
            _version = sagemaker.describe_endpoint(EndpointName=ENDPOINT)["EndpointConfigName"]
        except (ClientError, BotoCoreError):
            return "desconocida"
    return _version


def publicar(pedido: dict) -> None:
    conexion = conectar(RABBITMQ_URL)
    try:
        canal = conexion.channel()
        declarar(canal)
        canal.basic_publish(exchange="", routing_key=COLA, body=json.dumps(pedido, ensure_ascii=False),
                            properties=pika.BasicProperties(delivery_mode=2))  # 2 = persistente
    finally:
        conexion.close()


@app.post("/api/predict", dependencies=[Depends(requiere_clave)])
def predict(entrada: Entrada):
    fila = ",".join(str(getattr(entrada, c)) for c in COLUMNAS)   # el orden del entrenamiento
    t = time.perf_counter()
    try:
        r = runtime.invoke_endpoint(EndpointName=ENDPOINT, ContentType="text/csv", Body=fila)
    except ClientError as e:
        raise HTTPException(status_code=502, detail=f"SageMaker respondió: {e.response['Error']['Message']}")
    except BotoCoreError as e:
        raise HTTPException(status_code=503, detail=f"No se pudo llegar a SageMaker: {type(e).__name__}")
    probabilidad = float(r["Body"].read().decode().strip())
    resultado = {
        "id": uuid.uuid4().hex,
        "caso": CASO,
        "probabilidad": round(probabilidad, 4),
        "decision": CASOS[CASO]["decisiones"][int(probabilidad >= UMBRAL)],
        "umbral": UMBRAL,
        "version_modelo": version_modelo(),
        "latencia_sagemaker_ms": round((time.perf_counter() - t) * 1000),
    }
    # El texto sale anonimizado de aquí: ni Redis, ni la cola, ni los logs, ni NVIDIA ven el original.
    texto = anonimizar(entrada.texto)
    entrada_guardada = {c: getattr(entrada, c) for c in COLUMNAS}
    clave = f"prediccion:{resultado['id']}"
    # Se encola solo si se pidió texto. Así la prueba de carga (sin texto) mide SageMaker y no a NVIDIA.
    # En EP3 cada caso decide cuándo encolar: en fraude, por ejemplo, solo lo que va a revisión.
    resultado["estado_llm"] = "pendiente" if texto else "no_solicitado"
    almacen.hset(clave, mapping={**resultado, "entrada": json.dumps(entrada_guardada), "texto": texto})
    if texto:
        try:
            publicar({"id": resultado["id"], "caso": CASO, "texto": texto,
                      "prediccion": {"probabilidad": resultado["probabilidad"],
                                     "decision": resultado["decision"], **entrada_guardada}})
        except Exception as e:   # RabbitMQ caído: la predicción igual se entrega, sin texto del LLM
            resultado["estado_llm"] = "degradado"
            almacen.hset(clave, mapping={"estado_llm": "degradado", "motivo_llm": f"cola: {type(e).__name__}"})
    log(evento="prediccion", **resultado)
    return resultado


NUMERICOS = {"probabilidad": float, "umbral": float, "latencia_sagemaker_ms": int, "latencia_llm_ms": int}


@app.get("/api/predicciones/{id}", dependencies=[Depends(requiere_clave)])
def prediccion(id: str):
    guardada = almacen.hgetall(f"prediccion:{id}")
    if not guardada:
        raise HTTPException(status_code=404, detail="No existe esa predicción")
    guardada["entrada"] = json.loads(guardada["entrada"])
    return {k: NUMERICOS[k](v) if k in NUMERICOS else v for k, v in guardada.items()}


@app.get("/api/health")
def health():
    piezas = {}
    try:
        almacen.ping()
        piezas["base"] = "ok"
    except redis.RedisError as e:
        piezas["base"] = f"error: {type(e).__name__}"
    try:
        piezas["sagemaker"] = sagemaker.describe_endpoint(EndpointName=ENDPOINT)["EndpointStatus"]
    except (ClientError, BotoCoreError) as e:
        piezas["sagemaker"] = f"error: {type(e).__name__}"
    try:
        conexion = conectar(RABBITMQ_URL)
        canal = conexion.channel()
        declarar(canal)
        piezas["cola"] = {
            "estado": "ok",
            "pendientes": canal.queue_declare(queue=COLA, passive=True).method.message_count,
            "fallidos": canal.queue_declare(queue=COLA_FALLIDOS, passive=True).method.message_count,
        }
        conexion.close()
    except Exception as e:
        piezas["cola"] = {"estado": f"error: {type(e).__name__}"}
    try:
        piezas["llm"] = almacen.get("llm:estado") or "sin llamadas todavía"
    except redis.RedisError:
        piezas["llm"] = "desconocido"
    sano = piezas["base"] == "ok" and piezas["sagemaker"] == "InService" and piezas["cola"]["estado"] == "ok"
    return {"estado": "ok" if sano and piezas["llm"] in ("ok", "sin llamadas todavía") else "degradado",
            "caso": CASO, "endpoint": ENDPOINT, "piezas": piezas}
