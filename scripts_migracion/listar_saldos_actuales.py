"""Imprime el saldo actual de cada cuenta corriente. Solo lee Supabase."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from calculos import total_cargos

load_dotenv(RAIZ / ".env")


def configurar_consola() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def cargar(sb, tabla: str, columnas: str) -> list[dict]:
    filas = []
    inicio = 0
    while True:
        lote = sb.table(tabla).select(columnas).range(inicio, inicio + 999).execute().data or []
        filas.extend(lote)
        if len(lote) < 1000:
            return filas
        inicio += 1000


def main() -> None:
    configurar_consola()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    clientes = cargar(sb, "clientes", "id,nombre,es_distribuidor,porcentaje_ganancia")
    pedidos = cargar(
        sb,
        "pedidos",
        "cliente_id,total_venta_usd,costo_total_usd,ganancia_bruta_usd,ganancia_real_usd",
    )
    pagos = cargar(sb, "pagos", "cliente_id,monto_usd_descontado")

    pedidos_por_cliente: dict[int, list] = {}
    for pedido in pedidos:
        if pedido.get("cliente_id") is None:
            continue
        pedidos_por_cliente.setdefault(int(pedido["cliente_id"]), []).append(pedido)

    pagos_por_cliente: dict[int, float] = {}
    for pago in pagos:
        if pago.get("cliente_id") is None:
            continue
        cliente_id = int(pago["cliente_id"])
        pagos_por_cliente[cliente_id] = pagos_por_cliente.get(cliente_id, 0.0) + float(
            pago.get("monto_usd_descontado") or 0
        )

    print(f"{'Cliente':<32} Saldo actual USD")
    for cliente in sorted(clientes, key=lambda item: item["nombre"].casefold()):
        cliente_id = int(cliente["id"])
        comprado = total_cargos(pedidos_por_cliente.get(cliente_id, []), cliente)
        saldo = round(comprado - pagos_por_cliente.get(cliente_id, 0.0), 2)
        print(f"{cliente['nombre']:<32} {saldo:,.2f}")


if __name__ == "__main__":
    main()
