# L11 · Worker con la API de NVIDIA, cola, HTTPS y despliegue

## Qué vas a lograr

Este laboratorio es **el sistema de EP3 sin tu caso adentro**. Al terminarlo tienes en AWS, funcionando,
todo lo que pide la sección 2 del enunciado salvo tu front y tu microservicio de dominio: la predicción
de SageMaker, el LLM por la cola, el modo degradado, la anonimización, HTTPS, rate limiting, los logs en
CloudWatch y el pipeline que prueba y despliega. Después, en EP3, le agregas lo de tu caso.

```text
Usuario ──HTTPS──► Caddy (443) ──► api (FastAPI) ──invoke_endpoint──► SageMaker  l10-<caso>
                                       │  └──► Redis (predicciones y estado)
                                       └──► RabbitMQ  cola "llm" ──► worker ──HTTPS──► API de NVIDIA
                                                     └── cola "llm.fallidos" (lo que el worker no pudo)

GitHub: push a main ──► pytest ──► imagen en GHCR ──SSH──► la EC2 hace pull y reinicia
```

| Tramo | Min | Qué haces |
|---|---|---|
| **1** | 20 | Preparas la EC2: perfil de instancia, IP elástica, puertos, hop limit y Docker |
| **2** | 15 | Creas tu clave de NVIDIA y haces una llamada a mano |
| **3** | 30 | Levantas el sistema y sigues una predicción desde la API hasta el texto del LLM |
| **4** | 20 | Rompes el LLM a propósito y miras el modo degradado |
| **5** | 10 | Activas HTTPS con Caddy y sslip.io |
| **6** | 25 | Conectas el pipeline de GitHub Actions y miras los logs en CloudWatch |

**Lo que entregas en Pulso:** las respuestas de las cajas y, en el punto de control final, la URL HTTPS
de tu `/api/health`, una predicción con su texto del LLM y el último workflow en verde.

> **Es trabajo individual y se hace en tu casa.** Cada integrante del equipo hace su propio laboratorio, en
su propio Learner Lab y con su propia clave de NVIDIA. En EP3 el equipo despliega **un** sistema, pero
en la presentación las preguntas se dirigen a cualquiera: quien no haya hecho esto con sus manos no va a
poder responder el IE8 ni el IE13.

### El repositorio de la clase

Todo el código está en
[github.com/Umbingelelo/ity1102-l11-worker-llm](https://github.com/Umbingelelo/ity1102-l11-worker-llm).
No lo clonas directo: lo usas como **plantilla** para tener tu propia copia, porque el pipeline necesita
correr en un repositorio tuyo, con tus secretos.

| Archivo | Qué es |
|---|---|
| `app/main.py` | La API: `/api/predict`, `/api/predicciones/{id}`, `/api/health` y `/docs` |
| `app/worker.py` | El worker: consume la cola, llama al LLM y guarda el texto |
| `app/llm.py` | La llamada a NVIDIA con tiempo máximo, reintentos y espera creciente |
| `app/anonimizar.py` | Quita RUT, correo, teléfono y tarjeta antes de encolar |
| `app/cola.py` | La declaración de las dos colas, compartida por la API y el worker |
| `app/casos.py` | Las columnas de cada caso (las mismas de L10) y la instrucción del LLM |
| `compose.yaml` | Las cinco piezas: caddy, api, worker, rabbitmq, redis |
| `compose.aws.yaml` | Solo en la EC2: manda los logs a CloudWatch |
| `Caddyfile` | HTTPS y el enrutamiento de `/api/*` y `/docs` |
| `tests/` | 15 pruebas, entre ellas las seis obligatorias de EP3 |
| `locustfile.py` | La prueba de carga de EP3 |
| `.github/workflows/desplegar.yml` | prueba → construir → desplegar |

### Palabras que vas a ver hoy

| Palabra | Qué es |
|---|---|
| **Worker** | Un programa que no atiende usuarios: saca trabajos de una cola y los hace |
| **ack · nack** | El worker le avisa a RabbitMQ «terminé, bórralo» (ack) o «no pude» (nack) |
| **Dead letter queue** | La cola adonde van los mensajes que el worker rechazó. Aquí se llama `llm.fallidos` |
| **Backoff** | Esperar cada vez más entre reintentos: 2 s, 4 s, 8 s. Con **jitter** se le suma un poco al azar |
| **Modo degradado** | El sistema sigue respondiendo lo esencial (la predicción) cuando una pieza secundaria (el LLM) falla |
| **Rate limiting** | Un tope de solicitudes por minuto. Pasado el tope, la API responde `429` |
| **IMDS · hop limit** | El servicio de la EC2 que entrega las credenciales del rol, y cuántos saltos de red puede dar su respuesta. Un contenedor necesita 2 |
| **sslip.io** | Un DNS público que convierte `3-85-10-20.sslip.io` en la IP `3.85.10.20`. Te da un nombre sin comprar dominio |
| **GHCR** | El registro de imágenes Docker de GitHub, el mismo de L4 |

> Necesitas el **endpoint de tu caso de L10** (`l10-fraude`, `l10-chatbot` o `l10-recomendacion`) en
estado `InService`. Si lo borraste, vuelve a crearlo desde CloudShell con
`cd ~/ity1102-l10-sagemaker && python3 sagemaker/3_endpoint.py <tu caso>`: el modelo sigue en S3.

---

## Tramo 1 · La EC2

### 1.1 Lanzar la instancia

**EN AWS ACADEMY.** Learner Lab → **Start Lab** → **AWS**. Región **N. Virginia (`us-east-1`)**.

**EN LA CONSOLA.** EC2 → **Launch instance**, con estos valores. Lo que no aparece en la tabla se deja
como viene.

| Campo | Valor |
|---|---|
| Name | `l11-ep3` |
| AMI | **Ubuntu Server 24.04 LTS** |
| Instance type | `t3.medium` |
| Key pair | `vockey` |
| Network settings → **Edit** | Tres reglas de entrada: **SSH 22** desde `0.0.0.0/0`, **HTTP 80** desde `0.0.0.0/0`, **HTTPS 443** desde `0.0.0.0/0` |
| Configure storage | `20` GiB gp3 |
| Advanced details → **IAM instance profile** | `LabInstanceProfile` |
| Advanced details → **Metadata response hop limit** | `2` |

> **El puerto 22 abierto a todo internet es una deuda que declaras, no un descuido.** El runner de
GitHub Actions que despliega por SSH sale desde una IP distinta cada vez, y GitHub publica miles de
rangos: no caben en un security group. En EP3 lo escribes así en el informe, con la alternativa que lo
resolvería (un runner propio dentro de la EC2, o AWS Systems Manager). Lo que sí te protege: entrar
solo con la llave `vockey`, nunca con contraseña, y que **ningún otro puerto** esté abierto. RabbitMQ,
Redis y la API no se publican hacia afuera.

### 1.2 IP elástica

Sin IP elástica, la IP de la EC2 cambia cada vez que el Learner Lab se reinicia, y con ella cambian tu
URL HTTPS y el secreto `EC2_HOST` del pipeline. Lo viviste en L4.

EC2 → **Elastic IPs** → **Allocate Elastic IP address** → **Allocate**. Selecciónala → **Actions** →
**Associate Elastic IP address** → tu instancia `l11-ep3` → **Associate**. Anota la IP: de aquí en
adelante la llamamos `TU-IP`.

### 1.3 El hop limit, si te lo saltaste

Si al lanzar no encontraste **Metadata response hop limit**, o ya tenías la instancia creada, lo cambias
desde **CloudShell**:

```bash
ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=l11-ep3 Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text)
aws ec2 modify-instance-metadata-options --instance-id "$ID" --http-put-response-hop-limit 2 --http-endpoint enabled
```

**Lo visible:** un JSON con `"HttpPutResponseHopLimit": 2`.

En L10 el contenedor usaba `network_mode: host` y hablaba con el servicio de metadatos (IMDS) como si
fuera la propia EC2: un salto. Hoy la API corre en la red de Compose, como tu gateway de EP2, y la
respuesta del IMDS tiene que dar **dos** saltos: hasta la EC2 y de ahí al contenedor. Con el límite en 1,
la respuesta se pierde en el camino y `boto3` dice que no encuentra credenciales.

### 1.4 Entrar e instalar Docker

**EN TU TERMINAL** (en la carpeta donde está `labsuser.pem`):

```bash
chmod 400 labsuser.pem
ssh -i labsuser.pem ubuntu@TU-IP
```

**EN LA EC2:**

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu
exit
```

Vuelve a entrar con el mismo `ssh` (el grupo `docker` se aplica al iniciar sesión) y comprueba:

```bash
docker compose version
curl -s http://169.254.169.254/latest/meta-data/iam/info -H "X-aws-ec2-metadata-token: $(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')"
```

**Lo visible:** `Docker Compose version v2.` y un número, y un JSON con `"Code" : "Success"` y un
`InstanceProfileArn` que termina en `LabInstanceProfile`. Si el segundo comando no muestra nada, la
instancia no tiene el perfil: **Actions** → **Security** → **Modify IAM role** → `LabInstanceProfile`.

**Pregunta 1.1** (se responde en Pulso)
Pega la salida del segundo comando. Explica con tus palabras: ¿por qué en este sistema no hay ninguna
`AWS_ACCESS_KEY_ID` y aun así la API puede invocar SageMaker? ¿Qué pasaría con la predicción si el hop
limit siguiera en 1?


---

## Tramo 2 · Tu clave de NVIDIA

### 2.1 Crear la clave

Entra a [build.nvidia.com](https://build.nvidia.com) e inicia sesión (o crea una cuenta). Busca el
**modelo que publicó el docente en el foro** de la asignatura, ábrelo y haz clic en **Get API Key** →
**Generate Key**. Copia la clave: empieza con `nvapi-`. **Solo se muestra una vez.**

> La clave **no va nunca** en el código, en un commit, en un `Dockerfile` ni en un mensaje de WhatsApp del
equipo. Vive solo en el archivo `.env` del servidor. Si se te escapó a GitHub, bórrala en
build.nvidia.com y crea otra: borrar el commit no sirve, porque queda en el historial.

### 2.2 Una llamada a mano

**EN LA EC2.** `read -s` pide el valor sin mostrarlo en pantalla ni guardarlo en el historial de bash.
Pega tu clave y presiona Enter; después escribe el nombre del modelo del foro.

```bash
read -s -p "Clave NVIDIA: " NVIDIA_API_KEY; echo
read -p "Modelo del foro: " NVIDIA_MODEL
curl -s https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" -H 'content-type: application/json' \
  -d '{"model":"'"$NVIDIA_MODEL"'","messages":[{"role":"user","content":"Explica en una línea qué es un cold start"}],"max_tokens":120}' \
  -w '\nHTTP %{http_code} · %{time_total} s\n'
```

**Lo visible:** un JSON con `choices[0].message.content` y una línea como `HTTP 200 · 1.9 s`. Si sale
`HTTP 401`, la clave está mal copiada. Si sale `HTTP 404`, el nombre del modelo está mal escrito.

Repite el `curl` tres veces y anota los tres tiempos.

**Pregunta 2.1** (se responde en Pulso)
Anota los tres tiempos. Con el más lento: si tu API esperara al LLM antes de responder la predicción,
¿cuánto tardaría `/api/predict`? Compáralo con el requisito de rendimiento de tu caso (sección 3 del
enunciado de EP3). ¿Qué pasa con 41 usuarios en el mismo minuto si el límite gratuito ronda las 40
solicitudes por minuto?


---

## Tramo 3 · El sistema funcionando

### 3.1 Tu copia del repositorio

**EN GITHUB.** Abre
[github.com/Umbingelelo/ity1102-l11-worker-llm](https://github.com/Umbingelelo/ity1102-l11-worker-llm)
→ **Use this template** → **Create a new repository**. Dueño: tu usuario. Nombre:
**`ity1102-l11-worker-llm`** (el pipeline busca la carpeta con ese nombre en la EC2). Visibilidad:
**Public**. **Create repository**.

> Si en la pestaña **Actions** de tu repositorio aparece una ejecución con el job `desplegar` en rojo,
es esperable: todavía no creas los secretos. Lo arreglas en el tramo 6.

### 3.2 Clonar y configurar

**EN LA EC2** (cambia `TU-USUARIO`):

```bash
cd ~
git clone https://github.com/TU-USUARIO/ity1102-l11-worker-llm.git
cd ity1102-l11-worker-llm
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
nano .env
```

El `python3 -c` imprime una clave al azar: es la que va a pedir **tu** API en el header `X-API-Key`. En
`nano`, completa estas líneas y deja las demás como están. **Guardar:** Ctrl+O, Enter. **Salir:** Ctrl+X.

| Línea | Qué va |
|---|---|
| `CASO=` | `fraude`, `chatbot` o `recomendacion`, en minúsculas y sin tilde |
| `API_KEYS=` | La clave que acaba de imprimir el `python3 -c` |
| `NVIDIA_API_KEY=` | Tu clave `nvapi-…` |
| `NVIDIA_MODEL=` | El modelo del foro |

`ENDPOINT` se deja vacío: la API usa `l10-<tu caso>`. `DOMINIO` lo cambias en el tramo 5.

### 3.3 Levantar las cinco piezas

```bash
docker compose up -d --build
docker compose ps
```

La primera vez tarda unos minutos: construye la imagen y baja RabbitMQ, Redis y Caddy. **Lo visible:**
cinco servicios `Up`, y `rabbitmq` y `redis` con `(healthy)`.

Ahora, la salud de cada pieza. Por ahora le hablas a Caddy en la misma máquina, con el nombre
`localhost`: Caddy le pone un certificado propio que ningún navegador reconoce, y por eso el `-k` (no
verificar el certificado). El HTTPS de verdad llega en el tramo 5. Guarda la dirección en `B` para no
repetirla:

```bash
B=https://localhost
curl -sk $B/api/health | python3 -m json.tool
```

**Lo visible:**

```text
{
    "estado": "ok",
    "caso": "fraude",
    "endpoint": "l10-fraude",
    "piezas": {
        "base": "ok",
        "sagemaker": "InService",
        "cola": { "estado": "ok", "pendientes": 0, "fallidos": 0 },
        "llm": "sin llamadas todavía"
    }
}
```

Si `sagemaker` dice `error: NoCredentialsError`, vuelve al paso 1.3 (hop limit) y luego
`docker compose restart api`. Si dice `error: ClientError`, el endpoint `l10-<caso>` no existe.

### 3.4 Una predicción con texto

Guarda tu clave de API en una variable para no repetirla y manda la entrada de tu caso. El campo
`texto` trae datos personales a propósito.

```bash
K=$(grep ^API_KEYS= .env | cut -d= -f2 | cut -d, -f1)
```

Si tu caso es **fraude**:

```bash
curl -sk $B/api/predict -H "X-API-Key: $K" -H 'content-type: application/json' -d '{"monto_clp":250000,"hora":3,"intentos_previos_1h":4,"edad_cuenta_dias":12,"nivel_kyc":0,"usuarios_distintos":3,"emulador":1,"pais_distinto":1,"texto":"Soy Ana Pérez, RUT 12.345.678-9, no reconozco el cargo en mi tarjeta 4111 1111 1111 1111"}'
```

Si tu caso es **chatbot**:

```bash
curl -sk $B/api/predict -H "X-API-Key: $K" -H 'content-type: application/json' -d '{"turnos":18,"intentos_fallidos":2,"puntaje_molestia":0.7,"confianza_intencion":0.35,"deuda_vigente":150000,"antiguedad_meses":24,"texto":"Hola, soy Ana, RUT 12.345.678-9, llevo tres días sin internet, llámenme al +56 9 8765 4321"}'
```

Si tu caso es **recomendación**:

```bash
curl -sk $B/api/predict -H "X-API-Key: $K" -H 'content-type: application/json' -d '{"compras_previas":5,"ticket_promedio":120000,"precio_lista":90000,"categoria_vista":1,"ventas_30d":45,"texto":"Cliente ana.perez@correo.cl, mira notebooks y audífonos"}'
```

**Lo visible** (con fraude; tu `id` y tus números serán otros):

```text
{"id":"883efba2488c4effa3d95bc3f62abc42","caso":"fraude","probabilidad":0.9943,"decision":"revisar",
 "umbral":0.5,"version_modelo":"l10-fraude-…","latencia_sagemaker_ms":124,"estado_llm":"pendiente"}
```

La respuesta llegó **sin el texto del LLM**: `estado_llm` dice `pendiente`. Eso es el punto de la
arquitectura. Copia el `id` y pregunta por él un par de segundos después:

```bash
curl -sk $B/api/predicciones/PEGA-EL-ID -H "X-API-Key: $K" | python3 -m json.tool
```

**Lo visible:** el mismo resultado, más `"estado_llm": "listo"`, `texto_llm` con lo que redactó el
modelo, `latencia_llm_ms`, y el campo `texto` con `[RUT]`, `[TARJETA]`, `[TELEFONO]` o `[CORREO]` en
lugar de los datos originales.

Mira lo que dejaron la API y el worker en sus logs:

```bash
docker compose logs api worker --tail 5
```

**Pregunta 3.1** (se responde en Pulso)
Pega la respuesta de `/api/predict` y la de `/api/predicciones/{id}` con el texto del LLM. Responde:
¿qué recibió exactamente NVIDIA? (mira `prediccion` y `texto` en `publicar` de `app/main.py`). ¿Cuánto
tardó SageMaker y cuánto el LLM? ¿Por qué el usuario no tuvo que esperar los dos?


### 3.5 Las respuestas de seguridad

Tres peticiones malas. Cada una tiene que responder un código distinto:

```bash
curl -sk $B/api/predict -o /dev/null -w '%{http_code}\n' -H 'content-type: application/json' -d '{}'
curl -sk $B/api/predict -o /dev/null -w '%{http_code}\n' -H "X-API-Key: $K" -H 'content-type: application/json' -d '{"hora":"tarde"}'
for i in $(seq 1 65); do curl -sk $B/api/predict -o /dev/null -w '%{http_code} ' -H "X-API-Key: $K" -H 'content-type: application/json' -d '{}'; done; echo
```

**Lo visible:** `401`, `422`, y una fila de `422` que en algún momento pasa a `429`.

**Pregunta 3.2** (se responde en Pulso)
¿Por qué la primera petición da `401` y no `422`, si el cuerpo también está mal? ¿Por qué la ráfaga
cuenta peticiones con el cuerpo malo para el límite? Busca con `grep -n "LIMITE\|429" app/main.py`
dónde está el límite y cuánto vale.


---

## Tramo 4 · Romper el LLM a propósito

Esta es, casi palabra por palabra, la pregunta del **IE8** de la presentación de EP3.

### 4.1 Una clave inválida

```bash
sed -i 's/^NVIDIA_API_KEY=.*/NVIDIA_API_KEY=nvapi-invalida/' .env
docker compose up -d worker
```

`docker compose up -d worker` recrea el worker con el `.env` nuevo; `restart` no lo haría, porque
reinicia el mismo contenedor con las variables viejas. Ahora repite la predicción de tu caso del paso 3.4,
copia el `id` y pregunta por él y por la salud:

```bash
curl -sk $B/api/predicciones/PEGA-EL-ID -H "X-API-Key: $K" | python3 -m json.tool
curl -sk $B/api/health | python3 -m json.tool
docker compose logs worker --tail 3
```

**Lo visible:** la predicción respondió igual, con su probabilidad. En la consulta, `"estado_llm":
"degradado"` y `"motivo_llm": "HTTP 401"`. En la salud, `"fallidos": 1` y `"llm": "degradado: HTTP
401"`. En el log del worker, `"estado": "degradado"`.

### 4.2 El worker caído

Devuelve la clave buena y apaga el worker:

```bash
nano .env
docker compose stop worker
```

En `nano`, vuelve a poner tu clave real en `NVIDIA_API_KEY`. Repite la predicción con texto y mira la
salud: `"pendientes": 1`. Ahora levanta el worker y vuelve a preguntar por el `id`:

```bash
docker compose up -d worker
sleep 5
curl -sk $B/api/predicciones/PEGA-EL-ID -H "X-API-Key: $K" | python3 -m json.tool
```

**Lo visible:** `"estado_llm": "listo"`. El mensaje esperó en la cola mientras no había nadie para
atenderlo, y no se perdió.

**Pregunta 4.1** (se responde en Pulso)
Explica qué pasó con el mensaje en 4.1 y en 4.2. ¿Por qué en 4.1 terminó en `llm.fallidos` y no volvió
a la cola? ¿Por qué en 4.2 esperó? ¿En qué líneas de `app/llm.py` se decide que un `401` no se
reintenta y un `429` sí? ¿Cuántas veces, con qué espera, y con qué tiempo máximo por intento?


**Punto de control 1**
**Punto de control:** la predicción respondiendo con la clave de NVIDIA inválida, con
`estado_llm: degradado` y `fallidos` en 1 en `/api/health`. Guarda la captura: es la demostración del
IE8.

---

## Tramo 5 · HTTPS

### 5.1 Tu nombre en sslip.io

Tu nombre es tu IP elástica con **guiones** en vez de puntos, más `.sslip.io`. Si `TU-IP` es
`3.85.10.20`, el nombre es `3-85-10-20.sslip.io`. Compruébalo desde tu computador: `nslookup
3-85-10-20.sslip.io` devuelve `3.85.10.20`.

**EN LA EC2**, en `.env`, cambia `DOMINIO=localhost` por tu nombre y recrea Caddy:

```bash
nano .env
docker compose up -d caddy
docker compose logs caddy --tail 20
```

Caddy le pide un certificado a Let's Encrypt; Let's Encrypt comprueba que el nombre apunta a tu EC2
entrando por el puerto 80, y emite el certificado. **Lo visible** en el log, en menos de un minuto:
`certificate obtained successfully`.

Ahora, **desde tu navegador**: `https://TU-NOMBRE.sslip.io/docs`. Ves el candado y la documentación
de tu API. Desde ahora `B` es tu URL pública, con un certificado de verdad: el `-k` ya no hace falta,
pero no estorba.

```bash
B=https://TU-NOMBRE.sslip.io
curl -s $B/api/health | python3 -m json.tool
```

**Pregunta 5.1** (se responde en Pulso)
Pega tu URL de `/docs`. ¿Qué pasa si escribes `http://` en vez de `https://`? Si el puerto 80 estuviera
cerrado en el security group, ¿qué paso fallaría y por qué?


---

## Tramo 6 · El pipeline y los logs

### 6.1 Los cuatro secretos

Son los mismos de L4. **EN GITHUB**, en tu repositorio: **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**, cuatro veces:

| Nombre | Valor |
|---|---|
| `EC2_HOST` | `TU-IP` (la elástica) |
| `EC2_SSH_KEY` | El contenido completo de `labsuser.pem`, desde `-----BEGIN` hasta `-----END … KEY-----` |
| `GHCR_USUARIO` | Tu usuario de GitHub |
| `GHCR_PAT` | Un token clásico con permiso `read:packages`: tu foto → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)** |

> `NVIDIA_API_KEY` **no** va en GitHub. El pipeline no la necesita: la imagen no la trae, y el servidor la
lee de su propio `.env`, que el despliegue no toca. Cada secreto vive solo donde se usa.

### 6.2 Los logs a CloudWatch

Antes de que el pipeline despliegue por primera vez, levanta el sistema una vez a mano con el archivo
de CloudWatch, para comprobar que el rol puede escribir logs:

```bash
cd ~/ity1102-l11-worker-llm
echo "COMPOSE_FILE=compose.yaml:compose.aws.yaml" >> .env
docker compose up -d
docker compose ps
```

La línea `COMPOSE_FILE` del `.env` hace que **todo** `docker compose` de esta carpeta use los dos
archivos, sin escribir `-f` cada vez. Sin ella, el próximo `docker compose up -d worker` que escribas
recrearía el worker sin CloudWatch.

Si `api` o `worker` no quedan `Up` y `docker compose logs api` habla de `awslogs` o de
`AccessDenied`, avisa al docente con el mensaje: el rol no deja escribir logs. Mientras tanto, borra la
línea `COMPOSE_FILE` del `.env` y vuelve a `docker compose up -d`.

Haz una predicción con texto y busca su `id` en la consola: **CloudWatch** → **Log groups** →
`/ity1102/l11` → stream `api` → **Filter events**, pega el `id`.

**Lo visible:** una línea JSON con `"evento": "prediccion"`, tu `id`, la probabilidad, la versión del
modelo y la latencia. Es la pregunta del IE13: «muéstrame en CloudWatch el log de la predicción que
acabo de hacer».

### 6.3 Un push que llega solo a la EC2

**EN TU COMPUTADOR**, clona tu repositorio, cambia el título de la API y sube el cambio a `main`:

```bash
git clone https://github.com/TU-USUARIO/ity1102-l11-worker-llm.git
cd ity1102-l11-worker-llm
sed -i.bak 's/L11 · microservicio de IA/L11 · TU-APELLIDO · microservicio de IA/' app/main.py && rm app/main.py.bak
git commit -am "Título con mi apellido"
git push
```

En **Actions** mira la ejecución: `prueba` (15 pruebas), `construir` (la imagen en GHCR) y `desplegar`
(SSH a la EC2: `git checkout`, `pull` de la imagen, `up -d`). Cuando esté en verde, recarga
`https://TU-NOMBRE.sslip.io/docs`: el título trae tu apellido.

**Pregunta 6.1** (se responde en Pulso)
Pega el log del paso **Run pytest -v** del job `prueba` (las 15 líneas `PASSED`). Indica cuáles de esas
pruebas son las seis obligatorias de la sección 4.3 de EP3. Después explica: ¿qué tendría que pasar
para que tu cambio **no** llegara al servidor?


### 6.4 Rompe una prueba

Rompe la anonimización a propósito y súbela: en `app/anonimizar.py`, cambia `"[RUT]"` por `"[R]"`.

```bash
git commit -am "Rompo la anonimización a propósito"
git push
```

**Lo visible:** `prueba` en rojo con `test_ningun_dato_personal_sobrevive` fallando, `construir` y
`desplegar` en gris, y la API de la EC2 sin cambios. Revierte con `git revert --no-edit HEAD && git
push`.

**Pregunta 6.2** (se responde en Pulso)
¿Qué línea del log de la prueba te dice exactamente qué falló? Si en EP3 alguien del equipo sube un
cambio que hace que la API responda `500` ante una entrada inválida, ¿qué prueba lo detendría?


### 6.5 Apagar

El crédito del Learner Lab es tuyo y no se recarga. Al terminar: **EC2** → tu instancia → **Instance
state** → **Stop**. **No liberes la IP elástica** hasta después de la presentación de EP3: con la
instancia detenida cuesta unos US$ 0,12 al día, y sin ella tu URL y tu `EC2_HOST` cambian.

**Punto de control 2**
**Punto de control final:** en Pulso, la URL `https://…sslip.io/api/health` respondiendo, la respuesta
de `/api/predicciones/{id}` con `texto_llm`, la captura del workflow en verde y la captura de la línea
de la predicción en CloudWatch.

---

## Lo que esto tiene que ver con EP3

| Lo que hiciste hoy | Dónde se evalúa en EP3 |
|---|---|
| La predicción responde sin esperar al LLM | Regla 4 de 2.3 · IE8 |
| Clave inválida, worker caído, modo degradado | Regla 5 de 2.3 · pregunta del IE8 |
| `anonimizar.py` y su prueba | Regla 6 de 2.3 · prueba 5 de 4.3 · IE7 |
| `/api/health`, `/api/predict`, `/api/predicciones/{id}`, `/docs` | Tabla 2.5 · IE7 |
| `X-API-Key`, 422, 429, HTTPS | Mínimos de seguridad de 2.5 · IE7 |
| Las 15 pruebas en el pipeline | 4.3 · IE10 · pregunta del IE13 |
| La línea JSON en CloudWatch | Pregunta del IE13 · apartado 3 del informe |
| `locustfile.py` | Prueba de carga de 4.3 · pregunta del IE11 |

Para EP3 te faltan tres cosas, y las tres son de tu equipo: **tu modelo** (reentrenado con la salida de
`preparar.py`, con sus columnas en `app/casos.py`), **tu front y tu dominio** (detrás de Caddy, en el
`handle` que hoy responde un texto) y **las reglas de tu caso** (sección 3 del enunciado: cuándo se
encola, qué recibe el LLM y qué hace la API si SageMaker no responde a tiempo).

### Si algo no responde

| Señal | Causa probable | Qué hacer |
|---|---|---|
| `ssh: connect … Connection timed out` | Falta la regla del 22, o la EC2 está detenida | Revisa el security group y el estado de la instancia |
| `permission denied while trying to connect to the Docker daemon` | El grupo `docker` aún no se aplica | Sal con `exit` y vuelve a entrar por SSH |
| `required variable API_KEYS is missing` o `NVIDIA_MODEL` | Falta esa línea en `.env` | `nano .env` y complétala |
| `sagemaker: error: NoCredentialsError` | Hop limit en 1, o la EC2 sin `LabInstanceProfile` | Paso 1.3 o 1.4, y `docker compose restart api` |
| `sagemaker: error: ClientError` | El endpoint `l10-<caso>` no existe | `python3 sagemaker/3_endpoint.py <caso>` en CloudShell |
| `/api/predict` responde `503` | SageMaker no respondió en 10 s o sin credenciales | Mira `sagemaker` en `/api/health` |
| `estado_llm` se queda en `pendiente` | El worker no está corriendo | `docker compose ps` y `docker compose logs worker` |
| El worker muestra un `Traceback` con `AMQPConnectionError` | RabbitMQ se reinició | Se recupera solo: `restart: unless-stopped` lo levanta de nuevo |
| `motivo_llm: HTTP 404` | El nombre del modelo en `NVIDIA_MODEL` está mal | Cópialo de nuevo del foro y `docker compose up -d worker` |
| Caddy no obtiene el certificado | El 80 está cerrado, o `DOMINIO` no es tu IP elástica con guiones | Revisa el security group y el `.env` |
| `desplegar` en rojo con `ssh: handshake failed` | `EC2_SSH_KEY` incompleta o `EC2_HOST` con otra IP | Pega de nuevo el `.pem` entero y la IP elástica |
| `desplegar` en rojo con `No such file or directory` | El repositorio no está en `~/ity1102-l11-worker-llm` en la EC2 | Clónalo con ese nombre exacto (paso 3.2) |
| `desplegar` en rojo con `denied` al hacer `pull` | `GHCR_PAT` sin `read:packages` o vencido | Genera otro token y actualiza el secreto |
