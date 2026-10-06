import io
import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from supabase import Client

from calculos import parse_fecha, tiene_ficha
from database import cargar_todo, consultar, deuda_de_fichas, leer_clientes, leer_gastos, leer_productos
from ui import columna_usd, dinero, mostrar_kpis

ART = timezone(timedelta(hours=-3))
PERIODOS = ["Este mes", "Mes pasado", "Últimos 90 días", "Rango personalizado"]
TIPOS = ["Todos", "Solo distribuidores", "Solo estándar"]
TODAS_LAS_MARCAS = "Todas las marcas"
LINEA = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*[x×]\s*(.+?)\s*$", re.IGNORECASE)


def pagina_reportes(sb: Client) -> None:
    clientes = leer_clientes(sb)
    productos = leer_productos(sb, "id,nombre,marca,stock_actual,precio_puntero_usd")
    pedidos = consultar(
        sb,
        lambda cliente: cargar_todo(
            cliente,
            "pedidos",
            "id,cliente_id,fecha,total_venta_usd,costo_total_usd,ganancia_bruta_usd,ganancia_real_usd,detalle",
        ),
        "No se pudieron leer los pedidos del reporte.",
    )
    pagos = consultar(
        sb,
        lambda cliente: cargar_todo(cliente, "pagos", "cliente_id,monto_usd_descontado"),
        "No se pudieron leer los pagos del reporte.",
    )
    detalles = consultar(
        sb,
        lambda cliente: cargar_todo(
            cliente,
            "detalle_pedidos",
            "pedido_id,producto_id,cantidad,precio_unitario_cobrado",
        ),
        "No se pudo leer el detalle de productos.",
    )
    if None in (clientes, productos, pedidos, pagos, detalles):
        return

    clientes = sorted(clientes, key=lambda item: item["nombre"].lower())
    por_cliente = {int(item["id"]): item for item in clientes}
    por_producto = {int(item["id"]): item for item in productos}
    indice = catalogo_por_nombre(productos)
    guardadas = lineas_guardadas(detalles or [])
    hoy = datetime.now(ART).date()
    marcas = [TODAS_LAS_MARCAS] + sorted(
        {marca_de(item) for item in productos}
    )

    periodo = st.segmented_control(
        "Período",
        PERIODOS,
        default="Este mes",
        required=True,
        width="stretch",
    )
    with st.container(horizontal=True):
        tipo = st.selectbox("Tipo de cliente", TIPOS)
        visibles = [item for item in clientes if pasa_tipo(item, tipo)]
        opciones = [0] + [int(item["id"]) for item in visibles]
        if "reporte_cliente" in st.session_state and st.session_state["reporte_cliente"] not in opciones:
            st.session_state["reporte_cliente"] = 0
        cliente_id = st.selectbox(
            "Cliente",
            opciones,
            format_func=lambda valor: "Todos los clientes" if valor == 0 else por_cliente[valor]["nombre"],
            key="reporte_cliente",
        )
        marca = st.selectbox("Marca", marcas)

    inicio, fin = rango_del_periodo(periodo, hoy)
    if periodo == "Rango personalizado":
        with st.container(horizontal=True):
            desde = st.date_input(
                "Fecha desde",
                value=inicio,
                format="DD/MM/YYYY",
                key="reporte_fecha_desde",
            )
            hasta = st.date_input(
                "Fecha hasta",
                value=fin,
                format="DD/MM/YYYY",
                key="reporte_fecha_hasta",
            )
        if not isinstance(desde, date) or not isinstance(hasta, date):
            st.info("Elegí la fecha de inicio y la fecha de fin.")
            return
        inicio, fin = desde, hasta
        if inicio > fin:
            inicio, fin = fin, inicio

    del_periodo = [
        pedido
        for pedido in pedidos
        if pasa_pedido(pedido, por_cliente, cliente_id, tipo) and dentro(pedido.get("fecha"), inicio, fin)
    ]
    filas = ventas_por_producto(del_periodo, indice, por_producto, guardadas)
    if marca != TODAS_LAS_MARCAS:
        filas = [fila for fila in filas if fila["Marca"] == marca]

    if marca == TODAS_LAS_MARCAS:
        facturacion = round(sum(float(pedido.get("total_venta_usd") or 0) for pedido in del_periodo), 2)
        ganancia = round(sum(float(pedido.get("ganancia_real_usd") or 0) for pedido in del_periodo), 2)
    else:
        facturacion = round(sum(fila["Facturación"] for fila in filas), 2)
        ganancia = round(sum(fila["Ganancia"] for fila in filas), 2)

    por_deuda = {
        cliente_id_ficha: cliente
        for cliente_id_ficha, cliente in por_cliente.items()
        if tiene_ficha(cliente)
        and pasa_tipo(cliente, tipo)
        and (cliente_id == 0 or cliente_id_ficha == cliente_id)
    }
    deuda = deuda_de_fichas(pedidos, pagos, por_deuda)
    gastos = leer_gastos(sb, inicio, fin) or []
    total_gastos = round(sum(float(gasto.get("monto_usd") or 0) for gasto in gastos), 2)
    ganancia_neta = round(ganancia - total_gastos, 2)

    mostrar_kpis(
        [
            ("Facturación neta", dinero(facturacion), "A rendir en el período"),
            ("Ganancia limpia real", dinero(ganancia), "USD de la casa en el período"),
            ("Gastos Operativos", dinero(total_gastos), "Salidas del período, en USD"),
            ("Ganancia Neta Final", dinero(ganancia_neta), "Ganancia limpia menos gastos"),
            ("Deuda pendiente actual", dinero(deuda), "Cuentas con ficha propia"),
        ]
    )
    if cliente_id != 0 or marca != TODAS_LAS_MARCAS:
        st.caption(
            "Los gastos operativos son de toda la empresa en el período. "
            "La ganancia neta los resta de la ganancia filtrada."
        )

    meses = max(meses_del_rango(inicio, fin), 1)
    evolucion = evolucion_mensual(
        del_periodo, inicio, fin, marca, indice, por_producto, guardadas
    )

    pestana_productos, pestana_evolucion = st.tabs(["Productos y reposición", "Evolución histórica"])
    with pestana_productos:
        mostrar_productos(filas, meses)
    with pestana_evolucion:
        mostrar_evolucion(evolucion)


def pasa_tipo(cliente: dict | None, tipo: str) -> bool:
    if tipo == "Todos":
        return True
    if not cliente:
        return False
    es_distribuidor = bool(cliente.get("es_distribuidor"))
    if tipo == "Solo distribuidores":
        return es_distribuidor
    return not es_distribuidor


def pasa_pedido(pedido: dict, por_cliente: dict, cliente_id: int, tipo: str) -> bool:
    if pedido.get("cliente_id") is None:
        return tipo == "Todos" and cliente_id == 0
    duenio = int(pedido["cliente_id"])
    if cliente_id not in (0, duenio):
        return False
    return pasa_tipo(por_cliente.get(duenio), tipo)


def rango_del_periodo(periodo: str, hoy: date) -> tuple[date, date]:
    if periodo == "Mes pasado":
        primero_actual = hoy.replace(day=1)
        fin = primero_actual - timedelta(days=1)
        return fin.replace(day=1), fin
    if periodo == "Últimos 90 días":
        return hoy - timedelta(days=89), hoy
    return hoy.replace(day=1), hoy


def dentro(valor, inicio: date, fin: date) -> bool:
    momento = parse_fecha(valor)
    if momento.year <= 1:
        return False
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ART)
    dia = momento.astimezone(ART).date()
    return inicio <= dia <= fin


def meses_del_rango(inicio: date, fin: date) -> int:
    return (fin.year - inicio.year) * 12 + fin.month - inicio.month + 1


def normalizar(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto))
    base = "".join(letra for letra in base if not unicodedata.combining(letra))
    base = base.casefold().replace("×", "x")
    base = re.sub(r"[^a-z0-9]+", " ", base)
    return " ".join(base.split())


def catalogo_por_nombre(productos: list) -> dict[str, dict]:
    indice = {}
    for producto in productos:
        clave = normalizar(producto["nombre"])
        if clave and clave not in indice:
            indice[clave] = producto
    return indice


def lineas_guardadas(detalles: list) -> dict[int, list]:
    grupos: dict[int, list] = {}
    for detalle in detalles:
        grupos.setdefault(int(detalle["pedido_id"]), []).append(detalle)
    return grupos


def parsear_detalle(texto: str, indice: dict[str, dict]) -> list[tuple[float, str, dict | None]]:
    lineas = []
    for parte in re.split(r",\s*(?=\d+\s*[x×])", str(texto or ""), flags=re.IGNORECASE):
        coincidencia = LINEA.match(parte.strip())
        if not coincidencia:
            continue
        cantidad = float(coincidencia.group(1).replace(",", "."))
        nombre = coincidencia.group(2).strip(" ,")
        if cantidad <= 0 or not nombre:
            continue
        lineas.append((cantidad, nombre, indice.get(normalizar(nombre))))
    return lineas


def marca_de(producto: dict | None) -> str:
    if not producto:
        return "Sin marca"
    return str(producto.get("marca") or "").strip() or "Sin marca"


def aportes_pedido(pedido: dict, indice: dict, por_id: dict, guardadas: dict[int, list]) -> list[dict]:
    total = float(pedido.get("total_venta_usd") or 0)
    ganancia = float(pedido.get("ganancia_real_usd") or 0)
    crudas = []
    guardadas_pedido = guardadas.get(int(pedido["id"]))
    if guardadas_pedido:
        for item in guardadas_pedido:
            producto = por_id.get(int(item["producto_id"])) if item.get("producto_id") is not None else None
            cantidad = float(item.get("cantidad") or 0)
            precio = float(item.get("precio_unitario_cobrado") or 0)
            peso = cantidad * precio if precio > 0 else cantidad
            nombre = producto["nombre"] if producto else f"Producto {item.get('producto_id')}"
            crudas.append((cantidad, nombre, producto, peso))
    else:
        for cantidad, nombre, producto in parsear_detalle(pedido.get("detalle"), indice):
            precio = float(producto.get("precio_puntero_usd") or 0) if producto else 0.0
            peso = cantidad * precio if precio > 0 else cantidad
            crudas.append((cantidad, nombre, producto, peso))
    if not crudas:
        return []
    total_pesos = sum(item[3] for item in crudas) or 1.0
    aportes = []
    for cantidad, nombre, producto, peso in crudas:
        parte = peso / total_pesos
        clave = f"id:{producto['id']}" if producto else f"suelto:{normalizar(nombre)}"
        aportes.append(
            {
                "clave": clave,
                "Producto": producto["nombre"] if producto else nombre,
                "Marca": marca_de(producto),
                "Unidades": cantidad,
                "Facturación": total * parte,
                "Ganancia": ganancia * parte,
                "stock": int(producto["stock_actual"] or 0) if producto else None,
            }
        )
    return aportes


def ventas_por_producto(pedidos: list, indice: dict, por_id: dict, guardadas: dict[int, list]) -> list[dict]:
    acumulado: dict[str, dict] = {}
    for pedido in pedidos:
        for aporte in aportes_pedido(pedido, indice, por_id, guardadas):
            fila = acumulado.setdefault(
                aporte["clave"],
                {
                    "Producto": aporte["Producto"],
                    "Marca": aporte["Marca"],
                    "Unidades": 0.0,
                    "Facturación": 0.0,
                    "Ganancia": 0.0,
                    "stock": aporte["stock"],
                },
            )
            fila["Unidades"] += aporte["Unidades"]
            fila["Facturación"] += aporte["Facturación"]
            fila["Ganancia"] += aporte["Ganancia"]
    return sorted(acumulado.values(), key=lambda fila: fila["Unidades"], reverse=True)


def mostrar_productos(filas: list[dict], meses: int) -> None:
    st.caption(
        "El sugerido compara el promedio mensual de unidades del período con el stock actual del depósito. "
        f"El período abarca {meses} mes{'es' if meses != 1 else ''}."
    )
    tabla = []
    for fila in filas:
        promedio = fila["Unidades"] / meses
        stock = fila["stock"]
        facturacion = fila["Facturación"]
        ganancia = fila["Ganancia"]
        margen = (ganancia / facturacion * 100) if facturacion else 0.0
        if stock is None:
            sugerido = None
        else:
            faltante = promedio - stock
            sugerido = math.ceil(faltante) if faltante > 0.05 else 0
        tabla.append(
            {
                "Producto": fila["Producto"],
                "Marca": fila["Marca"],
                "Unidades vendidas": round(fila["Unidades"], 2),
                "Facturación USD": round(facturacion, 2),
                "Ganancia USD": round(ganancia, 2),
                "Margen %": round(margen, 1),
                "Promedio mensual": round(promedio, 2),
                "Stock depósito": stock,
                "Sugerido de reposición": sugerido,
            }
        )
    columnas = [
        "Producto",
        "Marca",
        "Unidades vendidas",
        "Facturación USD",
        "Ganancia USD",
        "Margen %",
        "Promedio mensual",
        "Stock depósito",
        "Sugerido de reposición",
    ]
    cuadro = pd.DataFrame(tabla, columns=columnas)
    if cuadro.empty:
        st.info("No hay ventas con productos identificables en este período.")
    else:
        st.dataframe(
            cuadro,
            width="stretch",
            hide_index=True,
            column_config={
                "Facturación USD": columna_usd("Facturación USD"),
                "Ganancia USD": columna_usd("Ganancia USD"),
                "Margen %": st.column_config.NumberColumn("Margen %", format="%.1f%%"),
                "Promedio mensual": st.column_config.NumberColumn("Promedio mensual", format="%.2f"),
                "Stock depósito": st.column_config.NumberColumn("Stock depósito"),
                "Sugerido de reposición": st.column_config.NumberColumn("Sugerido de reposición"),
            },
        )
    botones_exportar(cuadro, "reposicion", "Reposicion")


def evolucion_mensual(
    pedidos: list,
    inicio: date,
    fin: date,
    marca: str,
    indice: dict,
    por_id: dict,
    guardadas: dict[int, list],
) -> pd.DataFrame:
    cubos: dict[str, dict] = {}
    cursor = inicio.replace(day=1)
    ultimo = fin.replace(day=1)
    while cursor <= ultimo:
        cubos[cursor.strftime("%Y-%m")] = {"Mes": cursor.strftime("%Y-%m"), "Facturación neta": 0.0, "Ganancia limpia": 0.0}
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    for pedido in pedidos:
        momento = parse_fecha(pedido.get("fecha"))
        if momento.year <= 1:
            continue
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=ART)
        clave = momento.astimezone(ART).strftime("%Y-%m")
        cubo = cubos.setdefault(clave, {"Mes": clave, "Facturación neta": 0.0, "Ganancia limpia": 0.0})
        if marca == TODAS_LAS_MARCAS:
            cubo["Facturación neta"] += float(pedido.get("total_venta_usd") or 0)
            cubo["Ganancia limpia"] += float(pedido.get("ganancia_real_usd") or 0)
            continue
        for aporte in aportes_pedido(pedido, indice, por_id, guardadas):
            if aporte["Marca"] != marca:
                continue
            cubo["Facturación neta"] += aporte["Facturación"]
            cubo["Ganancia limpia"] += aporte["Ganancia"]

    filas = []
    for clave in sorted(cubos):
        cubo = cubos[clave]
        filas.append(
            {
                "Mes": cubo["Mes"],
                "Facturación neta": round(cubo["Facturación neta"], 2),
                "Ganancia limpia": round(cubo["Ganancia limpia"], 2),
            }
        )
    return pd.DataFrame(filas)


def mostrar_evolucion(tabla: pd.DataFrame) -> None:
    if tabla.empty or float(tabla["Facturación neta"].sum() + tabla["Ganancia limpia"].sum()) == 0:
        st.info("No hay ventas en este período.")
    else:
        st.bar_chart(
            tabla,
            x="Mes",
            y=["Facturación neta", "Ganancia limpia"],
            stack=False,
            sort=False,
            height=360,
        )
    st.dataframe(
        tabla,
        width="stretch",
        hide_index=True,
        column_config={
            "Facturación neta": columna_usd("Facturación neta"),
            "Ganancia limpia": columna_usd("Ganancia limpia"),
        },
    )
    botones_exportar(tabla, "evolucion", "Evolucion")


def botones_exportar(tabla: pd.DataFrame, clave: str, hoja: str) -> None:
    csv = tabla.to_csv(index=False).encode("utf-8-sig")
    excel = io.BytesIO()
    tabla.to_excel(excel, index=False, sheet_name=hoja)
    with st.container(horizontal=True):
        st.download_button(
            "Exportar CSV",
            data=csv,
            file_name=f"{clave}_reportes.csv",
            mime="text/csv",
            icon=":material/download:",
            key=f"csv_{clave}",
        )
        st.download_button(
            "Exportar Excel",
            data=excel.getvalue(),
            file_name=f"{clave}_reportes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            key=f"xlsx_{clave}",
        )
