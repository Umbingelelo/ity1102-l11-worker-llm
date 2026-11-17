"""El worker: saca un pedido de la cola, le pide el texto al LLM y lo guarda junto a la predicción.

Nunca toma la decisión: la decisión ya la tomó el modelo de SageMaker en la API. El LLM solo redacta.
"""
import json
import os
import time

import redis

from app import llm
from app.casos import CASOS
from app.cola import COLA, conectar, declarar


def procesar(pedido: dict, almacen, redactar=llm.redactar) -> str:
    clave = f"prediccion:{pedido['id']}"
    # Idempotencia: si el worker murió después de guardar y antes del ack, RabbitMQ entrega el mismo
    # mensaje otra vez. No se vuelve a gastar una llamada al LLM.
    if almacen.hget(clave, "estado_llm") == "listo":
        return "listo"
    contenido = json.dumps({"prediccion": pedido["prediccion"], "texto": pedido.get("texto", "")},
                           ensure_ascii=False)
    t = time.perf_counter()
    try:
        texto = redactar(CASOS[pedido["caso"]]["instruccion"], contenido)
    except llm.LLMNoDisponible as e:
        almacen.hset(clave, mapping={"estado_llm": "degradado", "motivo_llm": str(e)})
        almacen.set("llm:estado", f"degradado: {e}")
        return "degradado"
    almacen.hset(clave, mapping={"estado_llm": "listo", "texto_llm": texto,
                                 "latencia_llm_ms": round((time.perf_counter() - t) * 1000)})
    almacen.set("llm:estado", "ok")
    return "listo"


def main():
    almacen = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    # heartbeat largo: con los reintentos, una llamada puede tardar más de un minuto, y mientras tanto
    # el worker no atiende la conexión. Con el heartbeat de 60 s RabbitMQ lo daría por muerto.
    conexion = conectar(os.environ["RABBITMQ_URL"], heartbeat=600)
    canal = conexion.channel()
    declarar(canal)
    canal.basic_qos(prefetch_count=1)   # de a un mensaje: el siguiente no llega hasta el ack

    def al_recibir(ch, metodo, _propiedades, cuerpo):
        pedido = json.loads(cuerpo)
        estado = procesar(pedido, almacen)
        print(json.dumps({"evento": "llm", "id": pedido["id"], "estado": estado}), flush=True)
        if estado == "listo":
            ch.basic_ack(delivery_tag=metodo.delivery_tag)
        else:
            # requeue=False: no vuelve a la cola (sería un bucle contra una clave mala), va a llm.fallidos
            ch.basic_nack(delivery_tag=metodo.delivery_tag, requeue=False)

    canal.basic_consume(queue=COLA, on_message_callback=al_recibir)
    print(f"Worker listo · modelo {llm.MODELO or '(falta NVIDIA_MODEL)'} · esperando en '{COLA}'", flush=True)
    canal.start_consuming()


if __name__ == "__main__":
    main()
