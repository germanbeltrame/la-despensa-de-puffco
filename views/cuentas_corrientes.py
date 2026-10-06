import io
from datetime import datetime

import pandas as pd
import streamlit as st
from fpdf import FPDF
from supabase import Client

from calculos import (
    cargo_cuenta,
    es_cuenta_distribuidor,
    formatear_fecha,
    movimientos_cuenta,
    parse_fecha,
    tiene_ficha,
    total_cargos,
)
from database import deuda_de_fichas, leer_cartera, leer_clientes, leer_detalles_pedidos, leer_productos
from ui import columna_usd, dinero, mostrar_kpis, mostrar_libro

TIPO_RESUMEN = "Sin Detalle (Resumido)"
TIPO_DETALLE = "Con Detalle (Analítico)"


def pagina_cuentas(sb: Client) -> None:
    clientes = leer_clientes(sb)
    if clientes is None:
        return
    if not clientes:
        st.warning("Todavía no hay clientes para consultar.")
        return
    cartera = leer_cartera(sb)
    if cartera is None:
        return
    pedidos, pagos = cartera
    por_id = {int(item["id"]): item for item in clientes}
    pedidos_por_cliente = _agrupar(pedidos)
    pagos_por_cliente = _agrupar(pagos)
    deuda = deuda_de_fichas(pedidos, pagos, por_id)
    impagos = pedidos_impagos(clientes, pedidos_por_cliente, pagos_por_cliente)
    promedio = promedio_dias(impagos)
    detalle_promedio = f"{len(impagos)} pedidos impagos" if impagos else "Sin pedidos impagos"
    mostrar_kpis(
        [
            ("Deuda global", dinero(deuda), "Cuentas con ficha propia"),
            ("Promedio días de deuda", f"{promedio:.1f} días", detalle_promedio),
        ]
    )
    if st.button("Exportar estado de deudas", icon=":material/download:"):
        dialogo_exportar(_tabla_resumen(clientes, pedidos_por_cliente, pagos_por_cliente), _tabla_detalle(impagos), deuda)

    cliente = _cabecera_cliente(clientes, pedidos_por_cliente, pagos_por_cliente)
    if cliente is None:
        return

    cid = int(cliente["id"])
    pedidos_cliente = pedidos_por_cliente.get(cid, [])
    pagos_cliente = pagos_por_cliente.get(cid, [])
    detalles = []
    if pedidos_cliente:
        detalles = leer_detalles_pedidos(sb, [int(item["id"]) for item in pedidos_cliente])
        if detalles is None:
            return
    productos = leer_productos(sb, "id,nombre")
    if productos is None:
        return
    nombres = {int(item["id"]): item["nombre"] for item in productos}
    por_pedido: dict[int, list] = {}
    for linea in detalles or []:
        por_pedido.setdefault(int(linea["pedido_id"]), []).append(linea)

    total_comprado = total_cargos(pedidos_cliente, cliente)
    total_pagos = round(sum(float(item.get("monto_usd_descontado") or 0) for item in pagos_cliente), 2)
    saldo = round(total_comprado - total_pagos, 2)
    detalle_compra = cliente["nombre"]
    if es_cuenta_distribuidor(cliente):
        detalle_compra = f"{cliente['nombre']} · menos su parte de la ganancia"
    mostrar_kpis(
        [
            ("Total comprado", dinero(total_comprado), detalle_compra),
            ("Total pagado", dinero(total_pagos), "Abonos en USD"),
            ("Saldo pendiente", dinero(saldo), "Cargo menos abonos"),
        ]
    )
    st.subheader("Estado de cuenta", icon=":material/menu_book:")
    mostrar_libro(movimientos_cuenta(pedidos_cliente, pagos_cliente, cliente, por_pedido, nombres))


def _cabecera_cliente(clientes: list, pedidos_por_cliente: dict, pagos_por_cliente: dict) -> dict | None:
    opciones = [int(item["id"]) for item in clientes]
    fijo = st.session_state.get("cuenta_cliente_fijo")
    if fijo not in opciones:
        fijo = None
    if fijo is not None:
        cliente = next(item for item in clientes if int(item["id"]) == int(fijo))
        saldo = _saldo_cliente(cliente, pedidos_por_cliente, pagos_por_cliente)
        with st.container(border=True):
            columna_nombre, columna_saldo, columna_liberar = st.columns([2.2, 1.3, 1.4], vertical_alignment="center")
            columna_nombre.markdown(f"**{cliente['nombre']}** [{_tipo_cliente(cliente)}]")
            columna_saldo.metric("Saldo pendiente", dinero(saldo))
            if columna_liberar.button("Cambiar / Liberar Cliente", width="stretch"):
                st.session_state["cuenta_cliente_fijo"] = None
                st.rerun()
        return cliente

    busqueda = st.text_input("Buscar cliente", placeholder="Nombre del cliente", key="cuenta_buscar")
    filtrados = [item for item in clientes if busqueda.strip().lower() in item["nombre"].lower()]
    if not filtrados:
        st.warning("Ningún cliente coincide con la búsqueda.")
        return None
    filtrados = sorted(filtrados, key=lambda item: item["nombre"].lower())
    opciones_filtradas = [int(item["id"]) for item in filtrados]
    if st.session_state.get("cuenta_cliente_id") not in opciones_filtradas:
        st.session_state["cuenta_cliente_id"] = opciones_filtradas[0]
    cliente_id = st.selectbox(
        "Cliente",
        opciones_filtradas,
        format_func=lambda valor: next(item["nombre"] for item in filtrados if int(item["id"]) == valor),
        key="cuenta_cliente_id",
    )
    if st.button("Fijar cliente", type="primary"):
        st.session_state["cuenta_cliente_fijo"] = int(cliente_id)
        st.rerun()
    return None


def _tipo_cliente(cliente: dict) -> str:
    return "Distribuidor" if es_cuenta_distribuidor(cliente) else "Cliente Estándar"


@st.dialog("Exportar estado de deudas", width="large")
def dialogo_exportar(resumen: pd.DataFrame, detalle: pd.DataFrame, deuda: float) -> None:
    st.session_state.setdefault("deuda_tipo_reporte", TIPO_RESUMEN)
    tipo = st.segmented_control(
        "Tipo de reporte",
        [TIPO_RESUMEN, TIPO_DETALLE],
        key="deuda_tipo_reporte",
    )
    analitico = tipo == TIPO_DETALLE
    tabla = detalle if analitico else resumen
    dinero_col = "Saldo vivo (USD)" if analitico else "Saldo pendiente (USD)"
    st.dataframe(
        tabla,
        hide_index=True,
        width="stretch",
        height=360,
        column_config={dinero_col: columna_usd(dinero_col.replace(" (USD)", ""))},
    )
    st.caption(f"Deuda global de las fichas: {dinero(deuda)}")
    nombre = "estado_deudas_analitico" if analitico else "estado_deudas_resumido"
    hoja = "Detalle" if analitico else "Resumen"
    titulo = "Estado de deudas con detalle" if analitico else "Estado de deudas resumido"
    with st.container(horizontal=True):
        st.download_button(
            "Exportar a Excel",
            data=_excel(tabla, hoja),
            file_name=f"{nombre}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/table:",
            key=f"xlsx_{nombre}",
        )
        st.download_button(
            "Exportar a PDF",
            data=_pdf(titulo, tabla),
            file_name=f"{nombre}.pdf",
            mime="application/pdf",
            icon=":material/picture_as_pdf:",
            key=f"pdf_{nombre}",
        )


def _tabla_resumen(clientes: list, pedidos_por_cliente: dict, pagos_por_cliente: dict) -> pd.DataFrame:
    filas = []
    for cliente in sorted(clientes, key=lambda item: item["nombre"].lower()):
        if not tiene_ficha(cliente):
            continue
        saldo = _saldo_cliente(cliente, pedidos_por_cliente, pagos_por_cliente)
        if abs(saldo) <= 0.009:
            continue
        filas.append({"Cliente": cliente["nombre"], "Saldo pendiente (USD)": saldo})
    return pd.DataFrame(filas, columns=["Cliente", "Saldo pendiente (USD)"])


def _tabla_detalle(impagos: list) -> pd.DataFrame:
    filas = [
        {
            "Cliente": item["cliente"],
            "Fecha": item["fecha"],
            "N° Pedido": item["pedido"],
            "Detalle": item["detalle"],
            "Saldo vivo (USD)": item["saldo"],
            "Días sin pago": item["dias"],
            "Antigüedad": item["antiguedad"],
        }
        for item in impagos
    ]
    return pd.DataFrame(
        filas,
        columns=["Cliente", "Fecha", "N° Pedido", "Detalle", "Saldo vivo (USD)", "Días sin pago", "Antigüedad"],
    )


def _excel(tabla: pd.DataFrame, hoja: str) -> bytes:
    archivo = io.BytesIO()
    tabla.to_excel(archivo, index=False, sheet_name=hoja)
    return archivo.getvalue()


def _pdf(titulo: str, tabla: pd.DataFrame) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_font("helvetica", size=10)
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, titulo, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=9)
    pdf.cell(
        0,
        6,
        f"La Despensa de PUFFCO · {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)
    pdf.set_font("helvetica", size=8)
    columnas = list(tabla.columns)
    pesos = _pesos_columnas(columnas)
    with pdf.table(col_widths=pesos, text_align="LEFT", line_height=5, repeat_headings=1) as reporte:
        encabezado = reporte.row()
        for columna in columnas:
            encabezado.cell(columna)
        for _, fila in tabla.iterrows():
            linea = reporte.row()
            for columna in columnas:
                linea.cell(_texto_pdf(fila[columna], columna))
    return bytes(pdf.output())


def _pesos_columnas(columnas: list[str]) -> tuple[float, ...]:
    preferidos = {
        "Cliente": 3,
        "Fecha": 2.2,
        "N° Pedido": 1.4,
        "Detalle": 6,
        "Saldo pendiente (USD)": 2,
        "Saldo vivo (USD)": 1.8,
        "Días sin pago": 1.6,
        "Antigüedad": 1.6,
    }
    return tuple(preferidos.get(columna, 2) for columna in columnas)


def _texto_pdf(valor, columna: str) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, str):
        texto = valor.replace("🟢 ", "").replace("🟡 ", "").replace("🔴 ", "")
        if columna == "Detalle" and len(texto) > 180:
            return texto[:177] + "..."
        return texto
    if "USD" in columna:
        return dinero(valor)
    if columna == "Días sin pago":
        return str(int(valor))
    return str(valor)


def pedidos_impagos(clientes: list, pedidos_por_cliente: dict, pagos_por_cliente: dict) -> list[dict]:
    """Pedidos con saldo vivo de las cuentas con ficha, del más antiguo al más nuevo."""
    vivos = []
    for cliente in clientes:
        if not tiene_ficha(cliente):
            continue
        cid = int(cliente["id"])
        pedidos = pedidos_por_cliente.get(cid, [])
        restante = aplicar_pagos(pedidos, pagos_por_cliente.get(cid, []), cliente)
        for pedido in pedidos:
            saldo = round(restante.get(int(pedido["id"]), 0.0), 2)
            if saldo <= 0.009:
                continue
            dias = dias_desde(pedido.get("fecha"))
            vivos.append(
                {
                    "cliente": cliente["nombre"],
                    "orden": cliente["nombre"].lower(),
                    "cuando": parse_fecha(pedido.get("fecha")),
                    "fecha": formatear_fecha(pedido.get("fecha")),
                    "pedido": int(pedido["id"]),
                    "detalle": str(pedido.get("detalle") or "").split(" | ")[0].strip() or f"Pedido {pedido['id']}",
                    "saldo": saldo,
                    "dias": dias if dias is not None else 0,
                    "antiguedad": marca_antiguedad(dias),
                }
            )
    vivos.sort(key=lambda item: (item["orden"], item["cuando"], item["pedido"]))
    return vivos


def promedio_dias(impagos: list) -> float:
    if not impagos:
        return 0.0
    return round(sum(int(item["dias"]) for item in impagos) / len(impagos), 1)


def aplicar_pagos(pedidos: list, pagos: list, cliente: dict) -> dict[int, float]:
    """Saldo vivo de cada pedido.

    Los pagos positivos imputados bajan ese pedido; el resto se aplica del más
    antiguo al más nuevo. Un abono negativo devuelve saldo, primero al pedido
    imputado y después a los que se pagaron más recientemente.
    """
    ordenados = sorted(pedidos, key=lambda item: (parse_fecha(item.get("fecha")), int(item["id"])))
    original = {int(item["id"]): round(cargo_cuenta(item, cliente), 2) for item in ordenados}
    restante = dict(original)
    general = 0.0
    pagos_ordenados = sorted(pagos, key=lambda item: (parse_fecha(item.get("fecha")), int(item.get("id") or 0)))
    for pago in pagos_ordenados:
        usd = round(float(pago.get("monto_usd_descontado") or 0), 2)
        pedido_id = pago.get("pedido_id")
        if pedido_id is not None and int(pedido_id) in restante:
            pid = int(pedido_id)
            if usd >= 0:
                aplicado = min(max(restante[pid], 0.0), usd)
                restante[pid] = round(restante[pid] - aplicado, 2)
                usd = round(usd - aplicado, 2)
            else:
                espacio = round(original[pid] - restante[pid], 2)
                restaurar = min(max(espacio, 0.0), round(-usd, 2))
                restante[pid] = round(restante[pid] + restaurar, 2)
                usd = round(usd + restaurar, 2)
        general = round(general + usd, 2)
    for pedido in ordenados:
        if general <= 0:
            break
        pid = int(pedido["id"])
        aplicado = min(max(restante[pid], 0.0), general)
        restante[pid] = round(restante[pid] - aplicado, 2)
        general = round(general - aplicado, 2)
    if general < 0:
        devolver = round(-general, 2)
        for pedido in reversed(ordenados):
            if devolver <= 0:
                break
            pid = int(pedido["id"])
            pagado = round(original[pid] - restante[pid], 2)
            if pagado <= 0:
                continue
            restaurar = min(pagado, devolver)
            restante[pid] = round(restante[pid] + restaurar, 2)
            devolver = round(devolver - restaurar, 2)
    return restante


def dias_desde(valor) -> int | None:
    fecha = parse_fecha(valor)
    if fecha.year <= 1:
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone().replace(tzinfo=None)
    return max((datetime.now() - fecha).days, 0)


def marca_antiguedad(dias: int | None) -> str:
    if dias is None:
        return ""
    if dias <= 30:
        return "🟢 0-30"
    if dias <= 60:
        return "🟡 31-60"
    return "🔴 +60"


def _saldo_cliente(cliente: dict, pedidos_por_cliente: dict, pagos_por_cliente: dict) -> float:
    cid = int(cliente["id"])
    cargos = total_cargos(pedidos_por_cliente.get(cid, []), cliente)
    abonos = round(
        sum(float(item.get("monto_usd_descontado") or 0) for item in pagos_por_cliente.get(cid, [])),
        2,
    )
    return round(cargos - abonos, 2)


def _agrupar(filas: list) -> dict[int, list]:
    grupos: dict[int, list] = {}
    for fila in filas:
        if fila.get("cliente_id") is None:
            continue
        grupos.setdefault(int(fila["cliente_id"]), []).append(fila)
    return grupos


def _texto_pedido(pedido: dict, detalles: list, nombres: dict) -> str:
    partes = [
        f"{int(item['cantidad'])} x {nombres.get(int(item['producto_id']), 'Producto')}"
        for item in detalles
        if int(item.get("pedido_id") or 0) == int(pedido["id"]) and item.get("producto_id") is not None
    ]
    guardado = str(pedido.get("detalle") or "").split(" | ")[0].strip()
    return guardado or ", ".join(partes) or f"Pedido {pedido['id']}"
