import html
import io

import pandas as pd
import streamlit as st
from supabase import Client

from calculos import costo_unitario
from database import (
    actualizar_flete,
    eliminar_producto,
    esta_activo,
    guardar_producto,
    insertar_flete,
    leer_configuracion,
    leer_fletes,
    leer_productos,
    texto_error,
)
from ui import avisar, dinero, miniatura, mostrar_kpis, sembrar

COLUMNAS_PLANTILLA = [
    "Nombre",
    "Marca",
    "Categoría",
    "Costo_FOB",
    "Peso_KG",
    "Precio_KG",
    "Precio_Puntero",
    "Precio_Distro",
    "Stock_Ingreso",
    "URL_Imagen",
]


def tarifa_guardada(producto: dict | None, fletes: list) -> float:
    if not producto:
        return 0.0
    if producto.get("precio_kg") not in (None, ""):
        return float(producto["precio_kg"])
    if not producto.get("flete_id"):
        return 0.0
    for flete in fletes:
        if int(flete["id"]) == int(producto["flete_id"]):
            return float(flete.get("costo_usd_kg") or 0)
    return 0.0


def costo_visible(producto: dict, tarifa: float, fee_recepcion: float, fee_giro: float) -> float:
    if producto.get("calcular_costo") is False:
        if producto.get("costo_total_usd") not in (None, ""):
            return round(float(producto["costo_total_usd"]), 2)
        return 0.0
    return costo_unitario(
        producto.get("costo_fob") or 0,
        producto.get("peso_kg") or 0,
        tarifa,
        fee_recepcion,
        fee_giro,
    )


def flete_de_tarifa(sb: Client, fletes: list, tarifa: float) -> int | None:
    tarifa = round(float(tarifa), 2)
    for flete in fletes:
        if abs(float(flete.get("costo_usd_kg") or 0) - tarifa) < 0.001:
            return int(flete["id"])
    try:
        insertar_flete(sb, f"USD {tarifa:.2f}/kg", tarifa)
    except Exception:
        return None
    frescos = leer_fletes(sb) or []
    fletes.clear()
    fletes.extend(frescos)
    for flete in frescos:
        if abs(float(flete.get("costo_usd_kg") or 0) - tarifa) < 0.001:
            return int(flete["id"])
    return None


def clave_nombre(nombre: str) -> str:
    return " ".join(str(nombre or "").casefold().split())


def numero_celda(valor, default: float = 0.0) -> float:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return default
    if isinstance(valor, str):
        limpio = valor.strip().replace(",", ".")
        if not limpio:
            return default
        valor = limpio
    try:
        return float(valor)
    except (TypeError, ValueError):
        return default


def producto_incompleto(producto: dict) -> bool:
    """Incompleto solo si falta el peso o el FOB no quedó verificado."""
    if producto.get("incompleto") is True:
        return True
    sin_peso = producto.get("peso_kg") in (None, "") or float(producto.get("peso_kg") or 0) == 0
    fob_verificado = float(producto.get("costo_fob") or 0) > 0
    return sin_peso or not fob_verificado


def plantilla_excel() -> bytes:
    ejemplo = pd.DataFrame(
        [
            {
                "Nombre": "Ejemplo Peak",
                "Marca": "PUFFCO",
                "Categoría": "VAPORIZADOR",
                "Costo_FOB": 100,
                "Peso_KG": 0.5,
                "Precio_KG": 30,
                "Precio_Puntero": 250,
                "Precio_Distro": 200,
                "Stock_Ingreso": 2,
                "URL_Imagen": "",
            }
        ],
        columns=COLUMNAS_PLANTILLA,
    )
    archivo = io.BytesIO()
    ejemplo.to_excel(archivo, index=False, sheet_name="Productos")
    return archivo.getvalue()


@st.dialog("Producto", width="large")
def dialogo_producto(
    sb: Client,
    fletes: list,
    producto: dict | None,
    fee_recepcion: float,
    fee_giro: float,
) -> None:
    sufijo = "nuevo" if producto is None else str(int(producto["id"]))
    claves = {
        "nombre": f"prod_nombre_{sufijo}",
        "marca": f"prod_marca_{sufijo}",
        "categoria": f"prod_categoria_{sufijo}",
        "fob": f"prod_fob_{sufijo}",
        "peso": f"prod_peso_{sufijo}",
        "precio_kg": f"prod_precio_kg_{sufijo}",
        "calcular": f"prod_calcular_{sufijo}",
        "costo": f"prod_costo_{sufijo}",
        "puntero": f"prod_puntero_{sufijo}",
        "distro": f"prod_distro_{sufijo}",
        "stock": f"prod_stock_{sufijo}",
        "imagen": f"prod_imagen_{sufijo}",
        "activo": f"prod_activo_{sufijo}",
    }
    tarifa_inicial = tarifa_guardada(producto, fletes)
    costo_inicial = 0.0 if producto is None else costo_visible(producto, tarifa_inicial, fee_recepcion, fee_giro)
    sembrar(claves["nombre"], "" if producto is None else producto["nombre"])
    sembrar(claves["marca"], "PUFFCO" if producto is None else (producto.get("marca") or ""))
    sembrar(claves["categoria"], "VAPORIZADOR" if producto is None else (producto.get("categoria") or ""))
    sembrar(claves["fob"], 0.0 if producto is None else float(producto.get("costo_fob") or 0))
    sembrar(claves["peso"], 0.0 if producto is None else float(producto.get("peso_kg") or 0))
    sembrar(claves["precio_kg"], tarifa_inicial)
    sembrar(claves["calcular"], True if producto is None else producto.get("calcular_costo") is not False)
    sembrar(claves["costo"], costo_inicial)
    sembrar(claves["puntero"], 0.0 if producto is None else float(producto.get("precio_puntero_usd") or 0))
    sembrar(claves["distro"], 0.0 if producto is None else float(producto.get("precio_distro_usd") or 0))
    sembrar(claves["stock"], 0 if producto is None else int(producto.get("stock_actual") or 0))
    sembrar(claves["imagen"], "" if producto is None else (producto.get("imagen_url") or ""))
    sembrar(claves["activo"], True if producto is None else producto.get("activo") is not False)

    izquierda, derecha = st.columns(2)
    with izquierda:
        st.text_input("Nombre", key=claves["nombre"])
        st.text_input("Marca", key=claves["marca"])
        st.text_input("Categoría", key=claves["categoria"])
        st.number_input("Costo FOB (USD)", min_value=0.0, step=0.01, key=claves["fob"])
        st.number_input("Peso (kg)", min_value=0.0, step=0.001, format="%.3f", key=claves["peso"])
        st.number_input("Precio x KG (USD)", min_value=0.0, step=0.01, key=claves["precio_kg"])
    with derecha:
        st.number_input("Precio de venta (USD)", min_value=0.0, step=0.01, key=claves["puntero"])
        st.number_input("Precio distro (USD)", min_value=0.0, step=0.01, key=claves["distro"])
        st.number_input("Stock", min_value=0, step=1, key=claves["stock"])
        st.text_input("URL de la imagen", key=claves["imagen"], placeholder="Opcional")
        miniatura(str(st.session_state.get(claves["imagen"]) or "").strip(), 96)
        if producto is not None:
            st.checkbox("Activo", key=claves["activo"])

    calcular = st.checkbox("Calcular costo por fórmula", key=claves["calcular"])
    costo_formula = costo_unitario(
        st.session_state[claves["fob"]],
        st.session_state[claves["peso"]],
        st.session_state[claves["precio_kg"]],
        fee_recepcion,
        fee_giro,
    )
    if calcular:
        st.session_state[claves["costo"]] = costo_formula
    st.number_input(
        "Costo total (USD)",
        min_value=0.0,
        step=0.01,
        key=claves["costo"],
        disabled=calcular,
    )
    st.caption("(FOB + peso × precio por kg) × (1 + fees de recepción y giro).")

    if not st.button("Guardar", type="primary", key=f"guardar_producto_{sufijo}"):
        return
    nombre = " ".join(str(st.session_state[claves["nombre"]]).split())
    if not nombre:
        st.warning("El nombre del producto es obligatorio.")
        return
    precio_kg = round(float(st.session_state[claves["precio_kg"]]), 2)
    flete_id = flete_de_tarifa(sb, fletes, precio_kg)
    if flete_id is None:
        st.warning("No se pudo guardar el precio por kilo.")
        return
    datos = {
        "nombre": nombre,
        "marca": str(st.session_state[claves["marca"]]).strip() or "PUFFCO",
        "categoria": str(st.session_state[claves["categoria"]]).strip() or "VAPORIZADOR",
        "costo_fob": round(float(st.session_state[claves["fob"]]), 2),
        "peso_kg": round(float(st.session_state[claves["peso"]]), 3),
        "precio_kg": precio_kg,
        "flete_id": flete_id,
        "calcular_costo": bool(calcular),
        "costo_total_usd": round(float(st.session_state[claves["costo"]]), 2),
        "incompleto": (
            round(float(st.session_state[claves["peso"]]), 3) == 0
            or round(float(st.session_state[claves["fob"]]), 2) <= 0
        ),
        "precio_puntero_usd": round(float(st.session_state[claves["puntero"]]), 2),
        "precio_distro_usd": round(float(st.session_state[claves["distro"]]), 2),
        "stock_actual": int(st.session_state[claves["stock"]]),
        "imagen_url": str(st.session_state[claves["imagen"]]).strip() or None,
        "activo": True if producto is None else bool(st.session_state[claves["activo"]]),
    }
    error = guardar_producto(sb, datos, None if producto is None else int(producto["id"]))
    if error and error.startswith("Se guardó"):
        avisar("warning", error)
        return
    if error:
        st.error(error)
        return
    verbo = "agregado" if producto is None else "actualizado"
    avisar("success", f"Producto {nombre} {verbo}.")


@st.dialog("Eliminar producto")
def dialogo_borrar_producto(sb: Client, producto: dict) -> None:
    st.write(f"¿Eliminar **{producto['nombre']}**?")
    st.caption("Si ya se vendió, se desactiva y queda en los reportes.")
    if st.button("Eliminar", type="primary", key=f"confirmar_borrar_producto_{int(producto['id'])}"):
        resultado = eliminar_producto(sb, int(producto["id"]), producto.get("nombre") or "")
        if resultado:
            nivel, texto = resultado
            if nivel == "success":
                avisar("success", texto)
            elif nivel == "warning":
                st.warning(texto)
            else:
                st.error(texto)
            return
        avisar("success", f"Producto {producto['nombre']} eliminado.")


def texto_celda(valor, default: str = "") -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return default
    texto = str(valor).strip()
    if texto.lower() == "nan":
        return default
    return texto


def importar_productos(
    sb: Client,
    fletes: list,
    productos: list,
    filas: pd.DataFrame,
    fee_recepcion: float,
    fee_giro: float,
) -> tuple[int, int, list[str]]:
    faltantes = [columna for columna in COLUMNAS_PLANTILLA if columna not in filas.columns]
    if faltantes:
        return 0, 0, [f"Faltan columnas: {', '.join(faltantes)}."]
    por_clave = {clave_nombre(item.get("nombre") or ""): dict(item) for item in productos}
    creados = 0
    actualizados = 0
    errores: list[str] = []
    for indice, fila in filas.iterrows():
        numero = int(indice) + 2
        nombre = " ".join(texto_celda(fila["Nombre"]).split())
        if not nombre:
            errores.append(f"Fila {numero}: falta el nombre.")
            continue
        clave = clave_nombre(nombre)
        existente = por_clave.get(clave)
        fob = round(numero_celda(fila["Costo_FOB"]), 2)
        peso = round(numero_celda(fila["Peso_KG"]), 3)
        precio_kg = round(numero_celda(fila["Precio_KG"]), 2)
        ingreso = int(round(numero_celda(fila["Stock_Ingreso"])))
        url = texto_celda(fila["URL_Imagen"])
        flete_id = flete_de_tarifa(sb, fletes, precio_kg)
        if flete_id is None:
            errores.append(f"Fila {numero}: no se pudo guardar el precio por kilo de {nombre}.")
            continue
        calcular = True
        costo = costo_unitario(fob, peso, precio_kg, fee_recepcion, fee_giro)
        if existente and existente.get("calcular_costo") is False and existente.get("costo_total_usd") not in (None, ""):
            calcular = False
            costo = round(float(existente["costo_total_usd"]), 2)
        stock_base = int(existente.get("stock_actual") or 0) if existente else 0
        imagen = url or (existente.get("imagen_url") if existente else None) or None
        datos = {
            "nombre": existente["nombre"] if existente else nombre,
            "marca": texto_celda(fila["Marca"], "PUFFCO") or "PUFFCO",
            "categoria": texto_celda(fila["Categoría"], "VAPORIZADOR") or "VAPORIZADOR",
            "costo_fob": fob,
            "peso_kg": peso,
            "precio_kg": precio_kg,
            "flete_id": flete_id,
            "calcular_costo": calcular,
            "costo_total_usd": costo,
            "precio_puntero_usd": round(numero_celda(fila["Precio_Puntero"]), 2),
            "precio_distro_usd": round(numero_celda(fila["Precio_Distro"]), 2),
            "stock_actual": max(0, stock_base + ingreso),
            "imagen_url": imagen,
            "activo": True if existente is None else existente.get("activo") is not False,
            "incompleto": peso == 0 or fob <= 0,
        }
        error = guardar_producto(sb, datos, None if existente is None else int(existente["id"]))
        if error and not error.startswith("Se guardó"):
            errores.append(f"Fila {numero}: {error}")
            continue
        if existente is None:
            guardado = None
            try:
                hallados = (
                    sb.table("productos").select("*").eq("nombre", nombre).limit(1).execute().data or []
                )
                guardado = hallados[0] if hallados else None
            except Exception:
                guardado = None
            if guardado:
                por_clave[clave] = guardado
            else:
                por_clave[clave] = {**datos, "id": None, "stock_actual": datos["stock_actual"]}
            creados += 1
        else:
            existente.update(datos)
            actualizados += 1
        if error and error.startswith("Se guardó") and error not in errores:
            errores.append(error)
    return creados, actualizados, errores


@st.dialog("Importar productos", width="large")
def dialogo_importar(
    sb: Client,
    fletes: list,
    productos: list,
    fee_recepcion: float,
    fee_giro: float,
) -> None:
    st.caption(
        "Si el nombre ya existe, se suma el stock y se actualizan costos y precios. "
        "Si no existe, se crea el producto."
    )
    st.download_button(
        "Descargar plantilla Excel de ejemplo",
        data=plantilla_excel(),
        file_name="plantilla_productos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="descargar_plantilla_productos",
    )
    archivo = st.file_uploader("Archivo Excel", type=["xlsx"], key="archivo_importar_productos")
    if archivo is None or not st.button("Procesar archivo", type="primary", key="procesar_importacion"):
        return
    try:
        filas = pd.read_excel(archivo)
    except Exception as exc:
        st.error(f"No se pudo leer el Excel. {texto_error(exc)}")
        return
    creados, actualizados, errores = importar_productos(
        sb, fletes, productos, filas, fee_recepcion, fee_giro
    )
    if creados == 0 and actualizados == 0:
        st.error(errores[0] if errores else "El archivo no tiene productos para importar.")
        return
    resumen = f"Importación lista: {creados} nuevos y {actualizados} actualizados."
    if errores:
        avisar("warning", f"{resumen} {errores[0]}")
        return
    avisar("success", resumen)


def foto_valida(url) -> str:
    texto = str(url or "").strip()
    if texto.startswith("https://") or texto.startswith("http://"):
        return texto
    return ""


def celda_foto(url) -> None:
    foto = foto_valida(url)
    if foto:
        st.markdown(
            (
                f'<img src="{html.escape(foto, quote=True)}" width="40" height="40" '
                'style="object-fit:cover;border-radius:6px;display:block" alt="">'
            ),
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        '<div style="width:40px;height:40px;border:1px dashed #E4E4E7;border-radius:6px;background:#FAFAFA"></div>',
        unsafe_allow_html=True,
    )


def tabla_productos(
    sb: Client,
    fletes: list,
    filtrados: list,
    fee_recepcion: float,
    fee_giro: float,
) -> None:
    proporciones = [0.5, 1.9, 1.05, 1.1, 0.5, 1.25, 0.85, 0.95, 0.95]
    cabecera = st.columns(proporciones, vertical_alignment="center")
    for titulo, columna in zip(
        ["Foto", "Nombre", "Marca", "Categoría", "Stock", "Precio de venta", "Costo", "", ""],
        cabecera,
    ):
        if titulo:
            columna.markdown(f"**{titulo}**")

    with st.container(height=520):
        for item in filtrados:
            producto = item["producto"]
            pid = int(producto["id"])
            columnas = st.columns(proporciones, vertical_alignment="center")
            with columnas[0]:
                celda_foto(producto.get("imagen_url"))
            columnas[1].write(producto["nombre"])
            if producto_incompleto(producto):
                columnas[1].caption("⚠️ Incompleto")
            if not esta_activo(producto):
                columnas[1].caption("Inactivo")
            columnas[2].write(producto.get("marca") or "")
            columnas[3].write(producto.get("categoria") or "")
            stock = int(producto.get("stock_actual") or 0)
            columnas[4].write(str(stock))
            columnas[5].write(dinero(producto.get("precio_puntero_usd") or 0))
            columnas[6].write(dinero(item["costo"]))
            with columnas[7]:
                if st.button(
                    "Editar",
                    key=f"inv_editar_{pid}",
                    type="tertiary",
                    icon=":material/edit:",
                    width="stretch",
                ):
                    dialogo_producto(sb, fletes, producto, fee_recepcion, fee_giro)
            with columnas[8]:
                if st.button(
                    "Borrar",
                    key=f"inv_eliminar_{pid}",
                    type="tertiary",
                    icon=":material/delete:",
                    width="stretch",
                ):
                    dialogo_borrar_producto(sb, producto)


def pagina_inventario(sb: Client) -> None:
    fees = leer_configuracion(sb)
    fletes = leer_fletes(sb)
    productos = leer_productos(sb)
    if fees is None or fletes is None or productos is None:
        return

    fee = fees[0] if fees else None
    if fee is None:
        fee_recepcion, fee_giro = 3.5, 3.5
    else:
        fee_recepcion = float(fee["fee_recepcion_pct"])
        fee_giro = float(fee["fee_giro_pct"])

    catalogo = []
    for producto in productos:
        catalogo.append(
            {
                "producto": producto,
                "costo": costo_visible(
                    producto,
                    tarifa_guardada(producto, fletes),
                    fee_recepcion,
                    fee_giro,
                ),
            }
        )
    catalogo.sort(key=lambda item: item["producto"]["nombre"].lower())
    if not st.session_state.get("inv_inactivos", False):
        catalogo = [item for item in catalogo if esta_activo(item["producto"])]

    unidades = sum(int(item["producto"].get("stock_actual") or 0) for item in catalogo)
    valor_inventario = round(
        sum(int(item["producto"].get("stock_actual") or 0) * item["costo"] for item in catalogo),
        2,
    )
    sin_stock = sum(1 for item in catalogo if int(item["producto"].get("stock_actual") or 0) <= 0)
    mostrar_kpis(
        [
            ("Total de productos", str(len(catalogo)), "En el catálogo"),
            ("Valor de inventario", dinero(valor_inventario), "Costo de las unidades en stock"),
            ("Unidades", f"{unidades:,}", "Suma del stock actual"),
            ("Sin stock", str(sin_stock), "Productos en cero"),
        ]
    )

    categorias = sorted({(item["producto"].get("categoria") or "").strip() for item in catalogo if (item["producto"].get("categoria") or "").strip()})
    marcas = sorted({(item["producto"].get("marca") or "").strip() for item in catalogo if (item["producto"].get("marca") or "").strip()})
    opciones_categoria = ["Todas", *categorias]
    opciones_marca = ["Todas", *marcas]
    if st.session_state.get("inv_categoria") not in opciones_categoria:
        st.session_state["inv_categoria"] = "Todas"
    if st.session_state.get("inv_marca") not in opciones_marca:
        st.session_state["inv_marca"] = "Todas"

    col_buscar, col_categoria, col_marca, col_estado, col_inactivos = st.columns(
        [2.1, 1.3, 1.3, 1.4, 1.2],
        vertical_alignment="bottom",
    )
    with col_buscar:
        busqueda = st.text_input("Buscar", key="inv_buscar", placeholder="Nombre del producto")
    with col_categoria:
        categoria = st.selectbox("Categoría", opciones_categoria, key="inv_categoria")
    with col_marca:
        marca = st.selectbox("Marca", opciones_marca, key="inv_marca")
    with col_estado:
        completitud = st.selectbox("Productos", ["Todos", "Solo Incompletos"], key="inv_completitud")
    with col_inactivos:
        st.checkbox("Mostrar inactivos", key="inv_inactivos")

    col_alta, col_importar, _espacio = st.columns([1.3, 1.4, 3.3], vertical_alignment="bottom")
    with col_alta:
        if st.button("+ Nuevo producto", type="primary", width="stretch"):
            dialogo_producto(sb, fletes, None, fee_recepcion, fee_giro)
    with col_importar:
        if st.button("Importar Productos", width="stretch"):
            dialogo_importar(sb, fletes, productos, fee_recepcion, fee_giro)

    texto = busqueda.strip().lower()
    filtrados = []
    for item in catalogo:
        producto = item["producto"]
        if texto and texto not in producto["nombre"].lower():
            continue
        if categoria != "Todas" and (producto.get("categoria") or "").strip() != categoria:
            continue
        if marca != "Todas" and (producto.get("marca") or "").strip() != marca:
            continue
        if completitud == "Solo Incompletos" and not producto_incompleto(producto):
            continue
        filtrados.append(item)

    st.caption(f"{len(filtrados)} productos")

    if not catalogo:
        st.warning("Todavía no hay productos cargados.")
    elif not filtrados:
        st.warning("Ningún producto coincide con los filtros.")
    else:
        tabla_productos(sb, fletes, filtrados, fee_recepcion, fee_giro)

    with st.container(border=True):
        st.subheader("Gestión de fletes", icon=":material/local_shipping:")
        if not fletes:
            st.warning("No hay tipos de flete cargados.")
        else:
            editor = pd.DataFrame(fletes)[["id", "nombre", "costo_usd_kg"]]
            version = st.session_state.get("flete_version", 0)
            editado = st.data_editor(
                editor,
                hide_index=True,
                num_rows="fixed",
                key=f"editor_fletes_{version}",
                column_order=["nombre", "costo_usd_kg"],
                column_config={
                    "nombre": st.column_config.TextColumn("Tipo de flete", required=True),
                    "costo_usd_kg": st.column_config.NumberColumn(
                        "USD por kg",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                    ),
                },
            )
            if st.button("Guardar tarifas", type="primary"):
                try:
                    for indice, (_, fila) in enumerate(editado.iterrows()):
                        nombre_flete = str(fila["nombre"]).strip()
                        if not nombre_flete:
                            st.warning("Cada tipo de flete necesita un nombre.")
                            return
                        flete_id = int(fila["id"]) if "id" in editado.columns else int(fletes[indice]["id"])
                        actualizar_flete(sb, flete_id, nombre_flete, float(fila["costo_usd_kg"]))
                except Exception as exc:
                    st.error(f"No se pudieron guardar las tarifas. {texto_error(exc)}")
                else:
                    st.session_state["flete_version"] = version + 1
                    avisar(
                        "success",
                        "Tarifas actualizadas. El costo total se recalcula con la tarifa nueva y el FOB no cambia.",
                    )

        with st.form("nuevo_flete", clear_on_submit=True):
            st.markdown("**Nuevo tipo de flete**")
            nombre_nuevo = st.text_input("Nombre del flete")
            tarifa_nueva = st.number_input("Tarifa USD por kg", min_value=0.0, step=0.01)
            crear_flete = st.form_submit_button("Agregar tipo de flete")
        if crear_flete:
            if not nombre_nuevo.strip():
                st.warning("El nombre del flete es obligatorio.")
            else:
                try:
                    insertar_flete(sb, nombre_nuevo.strip(), float(tarifa_nueva))
                except Exception as exc:
                    st.error(f"No se pudo agregar el flete. {texto_error(exc)}")
                else:
                    st.session_state["flete_version"] = st.session_state.get("flete_version", 0) + 1
                    avisar("success", f"Tipo de flete {nombre_nuevo.strip()} agregado.")
