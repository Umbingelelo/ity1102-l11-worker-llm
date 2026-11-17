"""Quita los datos personales de un texto antes de que salga hacia NVIDIA.

El orden importa: la tarjeta va antes que el teléfono y el RUT, porque sus 16 dígitos contienen
secuencias que también parecen un teléfono o un RUT. Si se enmascara primero el teléfono, quedan
dígitos sueltos de la tarjeta en el texto.
"""
import re

PATRONES = [
    # correo: algo@dominio.cl
    ("[CORREO]", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    # tarjeta: 13 a 19 dígitos, con o sin espacios o guiones entre grupos
    ("[TARJETA]", re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")),
    # RUT: 12.345.678-9, 12345678-9, 9.876.543-K
    ("[RUT]", re.compile(r"(?<![\d.])\d{1,2}(?:\.?\d{3}){2}-[\dkK](?![\w])")),
    # teléfono chileno: +56 9 1234 5678, 56912345678, 912345678, (2) 2345 6789
    ("[TELEFONO]", re.compile(r"(?<!\d)(?:\+?56[ -]?)?\(?[2-9]\)?[ -]?\d{4}[ -]?\d{4}(?!\d)")),
]


def anonimizar(texto: str) -> str:
    for reemplazo, patron in PATRONES:
        texto = patron.sub(reemplazo, texto)
    return texto
