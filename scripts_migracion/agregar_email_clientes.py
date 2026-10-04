"""Agrega clientes.email si todavía no existe."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

SQL = """
alter table public.clientes add column if not exists email text;
create unique index if not exists clientes_email_unico
  on public.clientes (lower(email))
  where email is not null and email <> '';
"""


def configurar_consola() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def columna_existe(sb) -> bool:
    try:
        sb.table("clientes").select("email").limit(1).execute()
    except Exception as exc:
        mensaje = getattr(exc, "message", None) or str(exc)
        print(f"clientes.email: {exc.__class__.__name__}: {mensaje[:180]}")
        return False
    return True


def ejecutar_sql(url: str, clave: str) -> None:
    errores = []
    for ruta in ("/pg/query", "/pg-meta/default/query"):
        pedido = urllib.request.Request(
            url.rstrip("/") + ruta,
            data=json.dumps({"query": SQL}).encode(),
            headers={
                "apikey": clave,
                "Authorization": f"Bearer {clave}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(pedido, timeout=30) as respuesta:
                respuesta.read()
        except urllib.error.HTTPError as exc:
            errores.append(f"{ruta} respondió {exc.code}")
            continue
        except Exception as exc:
            errores.append(f"{ruta}: {exc.__class__.__name__}")
            continue
        return
    detalle = " ".join(errores) or "sin respuesta"
    raise RuntimeError(f"No se pudo ejecutar el SQL ({detalle}).")


def main() -> None:
    configurar_consola()
    raiz = Path(__file__).resolve().parents[1]
    load_dotenv(raiz / ".env")
    url = os.environ["SUPABASE_URL"].strip().strip('"')
    clave = os.environ["SUPABASE_KEY"].strip().strip('"')
    sb = create_client(url, clave)
    if columna_existe(sb):
        print("La columna email ya existe.")
        return
    try:
        ejecutar_sql(url, clave)
    except RuntimeError as exc:
        print(exc)
    if columna_existe(sb):
        print("Columna email creada en clientes.")
        return
    print("La clave de la API no puede alterar tablas.")
    print("Ejecutá este SQL en el editor de Supabase:")
    print(SQL.strip())
    raise SystemExit(1)


if __name__ == "__main__":
    main()
