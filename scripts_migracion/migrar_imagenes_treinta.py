"""Copia las fotos del catálogo de Treinta al campo imagen_url de productos.

Lee https://catalogo.treinta.co/ladespensapuffco y actualiza Supabase
emparejando por nombre. No crea productos ni toca precios ni stock.
"""

import json
import os
import sys
import unicodedata
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

CATALOGO = "https://catalogo.treinta.co/ladespensapuffco"
TIENDA = "b088b788-50f0-5abd-b76e-530f3a3c022c"
ACCION = "40543b8e804fdd9172d01b3e67327009946c1bac87"
LIMITE = 100


def configurar_consola() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def clave(nombre: str) -> str:
    texto = unicodedata.normalize("NFKD", nombre or "")
    texto = "".join(letra for letra in texto if not unicodedata.combining(letra))
    texto = texto.replace("\xa0", " ").replace("“", '"').replace("”", '"').replace("’", "'")
    return " ".join(texto.casefold().split())


def url_foto(producto: dict) -> str:
    valor = producto.get("imageUrl")
    if isinstance(valor, str) and valor.startswith("http"):
        return valor
    return ""


def leer_pagina(pagina: int) -> dict:
    cuerpo = json.dumps(
        [
            {
                "storeId": TIENDA,
                "page": pagina,
                "limit": LIMITE,
                "category": "$undefined",
                "search": "$undefined",
                "orderBy": "$undefined",
                "excludeOutOfStock": False,
            }
        ]
    ).encode()
    pedido = urllib.request.Request(
        CATALOGO,
        data=cuerpo,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "next-action": ACCION,
            "next-router-state-tree": (
                "%5B%22%22%2C%7B%22children%22%3A%5B%5B%22storeSlug%22%2C%22ladespensapuffco%22%2C%22d%22%5D%2C"
                "%7B%22children%22%3A%5B%22(shop)%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2Cnull%2Cnull%5D"
                "%7D%2Cnull%2Cnull%5D%2C%22modal%22%3A%5B%22__DEFAULT__%22%2C%7B%7D%2Cnull%2Cnull%5D%7D%2Cnull%2Cnull%5D"
                "%7D%2Cnull%2Cnull%2Ctrue%5D"
            ),
        },
        method="POST",
    )
    with urllib.request.urlopen(pedido, timeout=60) as respuesta:
        texto = respuesta.read().decode("utf-8", "replace")
    for linea in texto.splitlines():
        if linea.startswith("1:"):
            return json.loads(linea[2:])
    raise RuntimeError("Treinta no devolvió la lista de productos.")


def leer_catalogo() -> list[dict]:
    productos = []
    vistos = set()
    pagina = 1
    while pagina <= 50:
        lote = leer_pagina(pagina)
        for item in lote.get("data") or []:
            identificador = item.get("id")
            if identificador in vistos:
                continue
            vistos.add(identificador)
            productos.append(item)
        if not lote.get("hasNextPage"):
            return productos
        pagina += 1
    raise RuntimeError("El catálogo siguió paginando más de lo esperado.")


def leer_supabase(sb) -> list[dict]:
    filas = []
    inicio = 0
    while True:
        lote = (
            sb.table("productos")
            .select("id,nombre,imagen_url")
            .range(inicio, inicio + 999)
            .execute()
            .data
            or []
        )
        filas.extend(lote)
        if len(lote) < 1000:
            return filas
        inicio += 1000


def indice_por_nombre(filas: list[dict]) -> tuple[dict[str, dict], list[str]]:
    indice = {}
    repetidos = []
    for fila in filas:
        marca = clave(fila["nombre"])
        if not marca:
            continue
        if marca in indice:
            repetidos.append(fila["nombre"])
            indice.pop(marca, None)
            continue
        indice[marca] = fila
    return indice, repetidos


def main() -> None:
    configurar_consola()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    url = os.getenv("SUPABASE_URL", "").strip().strip('"')
    clave_api = os.getenv("SUPABASE_KEY", "").strip().strip('"')
    if not url or not clave_api:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en el archivo .env.")

    catalogo = leer_catalogo()
    con_foto = [item for item in catalogo if url_foto(item)]
    print(f"Productos en Treinta: {len(catalogo)}")
    print(f"Con foto: {len(con_foto)}")

    sb = create_client(url, clave_api)
    locales = leer_supabase(sb)
    indice, repetidos = indice_por_nombre(locales)
    print(f"Productos en Supabase: {len(locales)}")
    if repetidos:
        print(f"Nombres repetidos en Supabase, no se actualizan: {len(repetidos)}")

    actualizados = 0
    iguales = 0
    sin_par = []
    for item in con_foto:
        fila = indice.get(clave(item.get("name") or ""))
        if fila is None:
            sin_par.append(item.get("name") or "")
            continue
        foto = url_foto(item)
        if (fila.get("imagen_url") or "") == foto:
            iguales += 1
            continue
        sb.table("productos").update({"imagen_url": foto}).eq("id", int(fila["id"])).execute()
        actualizados += 1

    print(f"Actualizados: {actualizados}")
    print(f"Ya tenían esa foto: {iguales}")
    print(f"Sin producto equivalente en Supabase: {len(sin_par)}")
    for nombre in sin_par:
        print(f"  - {nombre}")


if __name__ == "__main__":
    main()
