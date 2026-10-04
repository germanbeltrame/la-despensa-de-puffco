"""Migración de clientes desde PUFFCO APP.xlsx hacia Supabase.

Muestra la lista propuesta y solo inserta si se confirma por consola.
"""

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

EXCEL = Path(__file__).resolve().parent / "PUFFCO APP.xlsx"

# Solapas de control. No son clientes.
SOLAPAS_INTERNAS = {
    "stock y price",
    "resumen",
    "lista special distro",
    "pedidos",
    "control de errores",
    "costo carga",
    "pesos",
    "compras proveedores",
    "cta cte total",
    "cta cte colo",
}

# Nombres que no deben entrar aunque aparezcan en Pedidos.
NOMBRES_EXCLUIDOS = {
    "colo",
    "cta cte colo",
    "clientes",
    "cliente",
    "nan",
    "none",
}

# Variantes que corresponden al mismo cliente.
ALIAS = {
    "ale ong": "ale ong cordoba",
    "coco salta 420": "coco salta",
    "lucas dedo de momia": "dedo de momia",
}

# Clave normalizada -> porcentaje de ganancia del socio.
SOCIOS = {
    "tin uy": 50.0,
    "pedro": 50.0,
    "charly distri": 50.0,
    "coco salta": 50.0,
    "agus honney": 50.0,
    "kanario": 50.0,
    "alan": 50.0,
    "guille naesa": 50.0,
    "facu pisando": 50.0,
    "old farmers": 50.0,
    "vaporever": 50.0,
    "lean tegridad": 50.0,
    "lt grow": 50.0,
    "conex distribuidora": 50.0,
}

ACRONIMOS = {
    "lp": "LP",
    "uy": "UY",
    "ong": "ONG",
    "omg": "OMG",
    "mdq": "MDQ",
    "nqn": "NQN",
    "lt": "LT",
}


def configurar_consola() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def clave(texto: str) -> str:
    limpio = " ".join(str(texto).replace("\xa0", " ").split())
    return limpio.casefold()


def presentar(texto: str) -> str:
    palabras = []
    for palabra in " ".join(str(texto).replace("\xa0", " ").split()).split():
        base = palabra.casefold()
        if base in ACRONIMOS:
            palabras.append(ACRONIMOS[base])
        else:
            palabras.append(base.capitalize())
    return " ".join(palabras)


def es_nombre_valido(texto) -> bool:
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return False
    nombre = " ".join(str(texto).replace("\xa0", " ").split())
    if not nombre or nombre.casefold() in NOMBRES_EXCLUIDOS:
        return False
    if nombre.casefold() in SOLAPAS_INTERNAS:
        return False
    return any(caracter.isalpha() for caracter in nombre)


def recolectar() -> tuple[list[dict], list[str]]:
    libro = pd.ExcelFile(EXCEL)
    solapas_clientes = [
        nombre
        for nombre in libro.sheet_names
        if clave(nombre) not in SOLAPAS_INTERNAS and es_nombre_valido(nombre)
    ]
    pedidos = pd.read_excel(EXCEL, sheet_name="Pedidos")
    if "Clientes" not in pedidos.columns:
        raise RuntimeError("La hoja Pedidos no tiene la columna Clientes.")

    crudos = []
    for solapa in solapas_clientes:
        crudos.append((solapa, f"solapa {solapa}"))
    for valor in pedidos["Clientes"].tolist():
        if es_nombre_valido(valor):
            crudos.append((str(valor), "Pedidos"))

    canonico_de_solapa = {clave(nombre): presentar(nombre) for nombre in solapas_clientes}
    grupos: dict[str, dict] = {}
    unificaciones = []

    for original, origen in crudos:
        limpio = " ".join(str(original).replace("\xa0", " ").split())
        destino = ALIAS.get(clave(limpio), clave(limpio))
        if destino in NOMBRES_EXCLUIDOS or destino in SOLAPAS_INTERNAS:
            continue
        visible = canonico_de_solapa.get(destino, presentar(limpio if destino == clave(limpio) else destino))
        if destino in ALIAS.values() and destino in canonico_de_solapa:
            visible = canonico_de_solapa[destino]
        grupo = grupos.setdefault(
            destino,
            {"nombre": visible, "origenes": [], "variantes": set()},
        )
        if destino in canonico_de_solapa:
            grupo["nombre"] = canonico_de_solapa[destino]
        grupo["variantes"].add(presentar(limpio))
        grupo["origenes"].append(origen)
        if destino != clave(limpio):
            unificaciones.append(f"{presentar(limpio)} -> {grupo['nombre']}")

    clientes = []
    for destino, grupo in grupos.items():
        porcentaje = SOCIOS.get(destino, 100.0)
        clientes.append(
            {
                "nombre": grupo["nombre"],
                "es_distribuidor": destino in SOCIOS,
                "porcentaje_ganancia": porcentaje,
                "variantes": sorted(grupo["variantes"], key=str.casefold),
            }
        )
    clientes.sort(key=lambda item: item["nombre"].casefold())
    unificaciones = sorted(set(unificaciones), key=str.casefold)
    return clientes, unificaciones


def imprimir_propuesta(clientes: list[dict], unificaciones: list[str]) -> None:
    print(f"Clientes únicos a migrar: {len(clientes)}")
    print("Todavía no se escribió nada en Supabase.")
    print()
    if unificaciones:
        print("Unificaciones de apodos o variantes:")
        for linea in unificaciones:
            print(f"  - {linea}")
        print()
    for indice, cliente in enumerate(clientes, start=1):
        marca = ""
        if cliente["es_distribuidor"]:
            marca = f"  [distribuidor {cliente['porcentaje_ganancia']:.0f}%]"
        print(f"{indice:3}. {cliente['nombre']}{marca}")
    socios = sum(1 for cliente in clientes if cliente["es_distribuidor"])
    print()
    print(f"Total: {len(clientes)} clientes, {socios} distribuidores.")


def confirmar() -> bool:
    print()
    try:
        respuesta = input("¿Insertar esta lista en Supabase? Escribí si para confirmar: ")
    except EOFError:
        print("Sin confirmación. No se insertó nada.")
        return False
    return respuesta.strip().casefold() in {"si", "sí", "s", "yes"}


def insertar(clientes: list[dict]) -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    url = os.getenv("SUPABASE_URL", "").strip().strip('"')
    clave_api = os.getenv("SUPABASE_KEY", "").strip().strip('"')
    if not url or not clave_api:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en el archivo .env.")

    sb = create_client(url, clave_api)
    filas = [
        {
            "nombre": cliente["nombre"],
            "es_distribuidor": cliente["es_distribuidor"],
            "porcentaje_ganancia": cliente["porcentaje_ganancia"],
        }
        for cliente in clientes
    ]
    respuesta = sb.table("clientes").upsert(filas, on_conflict="nombre").execute()
    guardados = respuesta.data or []
    print()
    print(f"Insertados o actualizados: {len(guardados)}")
    for fila in sorted(guardados, key=lambda item: item["nombre"].casefold()):
        marca = "distribuidor" if fila["es_distribuidor"] else "estándar"
        print(f"  - {fila['nombre']} ({marca}, {float(fila['porcentaje_ganancia']):.0f}%)")
    print(f"Total: {len(guardados)}")


def main() -> None:
    configurar_consola()
    if not EXCEL.exists():
        raise FileNotFoundError(f"No se encontró el Excel: {EXCEL}")
    clientes, unificaciones = recolectar()
    imprimir_propuesta(clientes, unificaciones)
    if not confirmar():
        return
    insertar(clientes)


if __name__ == "__main__":
    main()
