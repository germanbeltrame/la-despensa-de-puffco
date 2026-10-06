from datetime import datetime


def margen_porcentaje(precio, costo) -> float | None:
    """((precio de venta - costo total) / costo total) × 100. Sin costo no hay margen."""
    base = float(costo or 0)
    if base <= 0:
        return None
    return round((float(precio or 0) - base) / base * 100, 1)


def costo_unitario(fob, peso_kg, tarifa_kg, fee_recepcion_pct, fee_giro_pct) -> float:
    """(FOB + peso × precio por kg) × (1 + fees). Los fees entran como porcentaje."""
    flete = float(peso_kg) * float(tarifa_kg)
    base = float(fob) + flete
    gastos = base * (float(fee_recepcion_pct) + float(fee_giro_pct)) / 100
    return round(base + gastos, 2)


def factor_ganancia(cliente: dict) -> float:
    if cliente.get("es_distribuidor"):
        return float(cliente.get("porcentaje_ganancia") or 0) / 100
    return 1.0


def tiene_ficha(cliente: dict | None) -> bool:
    if not cliente:
        return False
    return bool(cliente.get("tiene_ficha"))


def es_cuenta_distribuidor(cliente: dict | None) -> bool:
    if not cliente:
        return False
    if cliente.get("es_distribuidor"):
        return True
    return float(cliente.get("porcentaje_ganancia") or 0) == 50.0


def cargo_cuenta(pedido: dict, cliente: dict | None = None) -> float:
    """Importe que se carga en la cuenta corriente.

    Si el total guardado ya es el neto a rendir (costo más la ganancia de la
    casa), ese total se cobra tal cual. Si el total sigue siendo el precio
    puntero, al distribuidor no se le cobra su parte de la ganancia.
    """
    total = float(pedido.get("total_venta_usd") or 0)
    bruta = float(pedido.get("ganancia_bruta_usd") or 0)
    real = float(pedido.get("ganancia_real_usd") or 0)
    costo = float(pedido.get("costo_total_usd") or 0)
    if (bruta - real) > 0.005 and abs(total - (costo + real)) <= 0.15:
        return round(total, 2)
    if abs(bruta - real) < 0.005 and es_cuenta_distribuidor(cliente):
        porcentaje = float(cliente.get("porcentaje_ganancia") or 50)
        real = round(bruta * porcentaje / 100, 2)
    return round(total - (bruta - real), 2)


def total_cargos(pedidos: list, cliente: dict | None = None) -> float:
    return round(sum(cargo_cuenta(pedido, cliente) for pedido in pedidos), 2)


def precio_de_venta(producto: dict, cliente: dict | None) -> tuple[float, str]:
    puntero = float(producto.get("precio_puntero_usd") or 0)
    distro = float(producto.get("precio_distro_usd") or 0)
    if cliente and cliente.get("es_distribuidor"):
        if distro > 0:
            return distro, "Precio distro"
        return puntero, "Precio puntero (sin precio distro)"
    return puntero, "Precio puntero"


def etiqueta_cliente(cliente: dict) -> str:
    return cliente["nombre"]


def parse_fecha(valor):
    if not valor:
        return datetime.min.replace(tzinfo=None)
    texto = str(valor).replace("Z", "+00:00")
    return datetime.fromisoformat(texto)


def _marca_orden(fecha: datetime) -> datetime:
    if fecha.tzinfo is not None:
        return fecha.replace(tzinfo=None)
    return fecha


def detalle_pago(pago: dict) -> str:
    moneda = str(pago.get("moneda") or "USD")
    original = float(pago.get("monto_original") or 0)
    if moneda == "ARS":
        texto = f"ARS {original:,.2f} · cotización {float(pago.get('cotizacion') or 0):,.2f}"
    else:
        texto = "USD"
    nota = str(pago.get("observaciones") or "").strip()
    if nota:
        return f"{texto}. {nota}"
    return texto


def detalle_pedido(pedido: dict, lineas: list, nombres: dict) -> str:
    partes = [
        f"{int(item.get('cantidad') or 0)} x {nombres.get(int(item['producto_id']), 'Producto')}"
        for item in lineas
        if item.get("producto_id") is not None
    ]
    armado = ", ".join(parte for parte in partes if not parte.startswith("0 x"))
    guardado = str(pedido.get("detalle") or "").strip()
    return armado or guardado or f"Pedido {pedido.get('id')}"


def movimientos_cuenta(
    pedidos: list,
    pagos: list,
    cliente: dict,
    detalles_por_pedido: dict,
    nombres: dict,
) -> list[dict]:
    """Libro de la cuenta, del movimiento más reciente al más antiguo.

    El saldo vivo se calcula en orden cronológico y queda en cada fila
    como el saldo después de esa operación.
    """
    filas = []
    for pedido in pedidos:
        pid = int(pedido["id"])
        filas.append(
            {
                "cuando": parse_fecha(pedido.get("fecha")),
                "orden": (0, pid),
                "Fecha": formatear_fecha(pedido.get("fecha")),
                "Tipo / Comprobante": f"Pedido #{pid}",
                "Detalle": detalle_pedido(pedido, detalles_por_pedido.get(pid, []), nombres),
                "importe": round(cargo_cuenta(pedido, cliente), 2),
            }
        )
    for pago in pagos:
        filas.append(
            {
                "cuando": parse_fecha(pago.get("fecha")),
                "orden": (1, int(pago.get("id") or 0)),
                "Fecha": formatear_fecha(pago.get("fecha")),
                "Tipo / Comprobante": "Pago aceptado",
                "Detalle": detalle_pago(pago),
                "importe": -round(float(pago.get("monto_usd_descontado") or 0), 2),
            }
        )
    filas.sort(key=lambda item: (_marca_orden(item["cuando"]), item["orden"]))
    saldo = 0.0
    for fila in filas:
        saldo = round(saldo + fila["importe"], 2)
        fila["Saldo vivo (US$)"] = saldo
    filas.reverse()
    return filas


def formatear_fecha(valor) -> str:
    fecha = parse_fecha(valor)
    if fecha.year <= 1:
        return ""
    return fecha.astimezone().strftime("%d/%m/%Y %H:%M")


def lineas_de_carrito(carrito: dict, productos: list, cliente: dict | None, flete_por_id: dict, fee_recepcion, fee_giro):
    por_id = {int(item["id"]): item for item in productos}
    lineas = []
    faltantes = []
    for producto_id, cantidad in carrito.items():
        producto = por_id.get(int(producto_id))
        if producto is None:
            faltantes.append(int(producto_id))
            continue
        tarifa = producto.get("precio_kg")
        if tarifa in (None, ""):
            flete = flete_por_id.get(int(producto["flete_id"])) if producto.get("flete_id") else None
            tarifa = float(flete["costo_usd_kg"]) if flete else 0.0
        else:
            flete = flete_por_id.get(int(producto["flete_id"])) if producto.get("flete_id") else None
            tarifa = float(tarifa)
        if producto.get("calcular_costo") is False:
            if producto.get("costo_total_usd") not in (None, ""):
                costo = round(float(producto["costo_total_usd"]), 2)
            else:
                costo = 0.0
        else:
            costo = costo_unitario(
                producto.get("costo_fob") or 0,
                producto.get("peso_kg") or 0,
                tarifa,
                fee_recepcion,
                fee_giro,
            )
        precio, origen_precio = precio_de_venta(producto, cliente)
        lineas.append(
            {
                "producto": producto,
                "cantidad": int(cantidad),
                "precio": precio,
                "origen_precio": origen_precio,
                "costo": costo,
                "tiene_flete": flete is not None,
            }
        )
    return lineas, faltantes
