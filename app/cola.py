"""La cola que comparten la API (publica) y el worker (consume).

Las dos piezas declaran la cola con los mismos argumentos. Si no coinciden, RabbitMQ rechaza la segunda
declaración con PRECONDITION_FAILED: por eso la declaración vive en un solo lugar.
"""
import pika

COLA = "llm"
COLA_FALLIDOS = "llm.fallidos"


def conectar(url: str, heartbeat: int = 60) -> pika.BlockingConnection:
    parametros = pika.URLParameters(url)
    parametros.connection_attempts = 1
    parametros.socket_timeout = 2
    parametros.blocked_connection_timeout = 5
    parametros.heartbeat = heartbeat
    return pika.BlockingConnection(parametros)


def declarar(canal) -> None:
    # Un mensaje que el worker rechaza con requeue=False no se pierde: RabbitMQ lo mueve a llm.fallidos
    # (la dead letter queue). Ahí queda a la vista para diagnosticar y, si se quiere, reprocesar.
    canal.queue_declare(queue=COLA_FALLIDOS, durable=True)
    canal.queue_declare(
        queue=COLA,
        durable=True,
        arguments={"x-dead-letter-exchange": "", "x-dead-letter-routing-key": COLA_FALLIDOS},
    )
