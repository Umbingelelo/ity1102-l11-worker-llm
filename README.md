# ITY1102 · L11 · Worker LLM, cola, HTTPS y despliegue

El esqueleto del sistema de EP3: una API FastAPI que predice con un endpoint serverless de SageMaker
y encola el texto del LLM; un worker que lo pide a la API de NVIDIA con reintentos y modo degradado;
RabbitMQ, Redis y Caddy con HTTPS. Las pruebas corren en GitHub Actions y el despliegue llega por SSH
a una EC2 del Learner Lab.

**La guía paso a paso está en [`LABORATORIO.md`](LABORATORIO.md).** Úsalo con **Use this template**:
el pipeline necesita correr en un repositorio tuyo, con tus secretos.

```text
Usuario ──HTTPS──► Caddy ──► api ──invoke_endpoint──► SageMaker  l10-<caso>
                              │ └──► Redis
                              └──► RabbitMQ "llm" ──► worker ──► API de NVIDIA
                                        └── "llm.fallidos"
```

## Rutas

| Método y ruta | Qué hace | Clave |
|---|---|---|
| `GET /api/health` | Estado de base, SageMaker, cola y LLM, por separado | No |
| `POST /api/predict` | Predice con SageMaker. Si trae `texto`, lo anonimiza y lo encola para el LLM | `X-API-Key` |
| `GET /api/predicciones/{id}` | La predicción guardada y, cuando llega, el texto del LLM | `X-API-Key` |
| `GET /docs` | OpenAPI (Swagger) | No |

## En la EC2

```bash
cp .env.example .env      # completa CASO, API_KEYS, NVIDIA_API_KEY, NVIDIA_MODEL, DOMINIO
docker compose up -d --build
curl -sk https://localhost/api/health
```

Requisitos: EC2 con `LabInstanceProfile`, *metadata response hop limit* en 2, puertos 22, 80 y 443, y
el endpoint `l10-<caso>` de L10 en `InService`.

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest -v
```

No llaman a AWS, a RabbitMQ ni a NVIDIA: cada pieza externa se reemplaza por un doble. Las seis
obligatorias de EP3 (sección 4.3) están en `tests/`, marcadas con su número.

## Prueba de carga

```bash
pip install locust==2.47.0
API_KEY=<tu clave> CASO=fraude locust -f locustfile.py --host https://<ip-con-guiones>.sslip.io \
  --headless -u 20 -r 5 -t 3m --csv carga
```

Sin `texto`, `/api/predict` no encola nada: la prueba mide tu sistema, no el límite de NVIDIA.

## Secretos

| Dónde | Qué |
|---|---|
| `.env` del servidor (nunca en Git) | `API_KEYS`, `NVIDIA_API_KEY` |
| GitHub → Settings → Secrets → Actions | `EC2_HOST`, `EC2_SSH_KEY`, `GHCR_USUARIO`, `GHCR_PAT` |
| Rol de la EC2 (`LabInstanceProfile`) | Las credenciales de AWS. No hay access keys en ninguna parte |
