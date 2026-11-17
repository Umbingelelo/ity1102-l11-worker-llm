"""Lo que cambia de un caso a otro: las columnas del modelo y para qué se usa el LLM.

Las columnas son las mismas de L10 y van en el mismo orden del entrenamiento. Si en EP3 reentrenas con
la salida de tu preparar.py, esta lista es lo primero que se actualiza.
"""

CASOS = {
    "rfm": {
        "columnas": ["recency", "frequency", "monetary"],
        "ejemplo": [10, 30, 800],
        "decisiones": ("cliente comun", "cliente de alta calidad"),
        "instruccion": (
            "Eres analista de marketing. Con la prediccion del modelo, escribe en dos lineas por que "
            "este cliente es o no es de alta calidad y que accion comercial conviene."
        ),
    },
    "fraude": {
        "columnas": ["monto_clp", "hora", "intentos_previos_1h", "edad_cuenta_dias",
                     "nivel_kyc", "usuarios_distintos", "emulador", "pais_distinto"],
        "ejemplo": [250000, 3, 4, 12, 0, 3, 1, 1],
        "decisiones": ("aprobar", "revisar"),
        "instruccion": (
            "Eres asistente de un analista de fraude. Con la decision del modelo y los datos de la "
            "transaccion, escribe un resumen de tres lineas en lenguaje comun para la cola de revision. "
            "No inventes datos y no tomes la decision: la decision ya la tomo el modelo."
        ),
    },
    "chatbot": {
        "columnas": ["turnos", "intentos_fallidos", "puntaje_molestia", "confianza_intencion",
                     "deuda_vigente", "antiguedad_meses"],
        "ejemplo": [18, 2, 0.7, 0.35, 150000, 24],
        "decisiones": ("sigue el bot", "derivar a ejecutivo"),
        "instruccion": (
            "Eres el asistente de atencion de una empresa de telecomunicaciones. Responde al mensaje "
            "del cliente en un maximo de tres lineas, en tono cordial. Si la decision es derivar a "
            "ejecutivo, avisale que lo atendera una persona."
        ),
    },
    "recomendacion": {
        "columnas": ["compras_previas", "ticket_promedio", "precio_lista", "categoria_vista", "ventas_30d"],
        "ejemplo": [5, 120000, 90000, 1, 45],
        "decisiones": ("no recomendar", "recomendar"),
        "instruccion": (
            "Eres redactor de campanas de e-commerce. Con la prediccion del modelo, escribe dos lineas "
            "de correo que expliquen por que se le recomienda este producto al cliente."
        ),
    },
}
