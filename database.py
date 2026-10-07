import os
import uuid
from datetime import date, timedelta, timezone
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client

from calculos import cargo_cuenta, parse_fecha, tiene_ficha


def texto_error(exc: Exception) -> str:
    mensaje = getattr(exc, "message", None) or str(exc)
    secreto = os.getenv("SUPABASE_KEY", "")
    if secreto:
        mensaje = mensaje.replace(secreto, "••••")
    return mensaje


def es_duplicado(exc: Exception) -> bool:
    texto = texto_error(exc).lower()
    return "duplicate" in texto or "23505" in texto


def es_en_uso(exc: Exception) -> bool:
    texto = texto_error(exc).lower()
    return "23503" in texto or "foreign key" in texto or "violates" in texto


def datos_cliente(nombre: str, es_distribuidor: bool) -> dict:
    return {
        "nombre": " ".join(nombre.split()),
        "es_distribuidor": bool(es_distribuidor),
        "porcentaje_ganancia": 50.0 if es_distribuidor else 100.0,
    }


def _credenciales() -> tuple[str, str]:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    url = os.getenv("SUPABASE_URL", "").strip().strip('"')
    clave = os.getenv("SUPABASE_KEY", "").strip().strip('"')
    if not url or not clave:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en el archivo .env.")
    return url, clave


def cliente_nuevo() -> Client:
    """Cliente sin caché. El de get_supabase no debe guardar el login de una persona."""
    url, clave = _credenciales()
    return create_client(url, clave)


@st.cache_resource
def get_supabase() -> Client:
    return cliente_nuevo()


def conectar() -> Client:
    sb = get_supabase()
    sb.table("configuracion").select("id").limit(1).execute()
    return sb


def consultar(sb: Client, accion, mensaje: str):
    try:
        return accion(sb)
    except Exception as exc:
        st.error(f"{mensaje} {texto_error(exc)}")
        return None


def cargar_todo(sb: Client, tabla: str, columnas: str = "*"):
    filas = []
    inicio = 0
    tamano = 1000
    while True:
        lote = (
            sb.table(tabla)
            .select(columnas)
            .range(inicio, inicio + tamano - 1)
            .execute()
            .data
            or []
        )
        filas.extend(lote)
        if len(lote) < tamano:
            return filas
        inicio += tamano


def leer_configuracion(sb: Client):
    return consultar(
        sb,
        lambda cliente: cliente.table("configuracion").select("*").limit(1).execute().data,
        "No se pudo leer la configuración.",
    )


def leer_clientes(sb: Client):
    return consultar(
        sb,
        lambda cliente: _con_columnas_cliente(
            COLUMNAS_CLIENTES,
            lambda columnas: cargar_todo(cliente, "clientes", columnas),
        ),
        "No se pudieron leer los clientes.",
    )


def leer_productos(sb: Client, columnas: str = "*"):
    return consultar(
        sb,
        lambda cliente: cargar_todo(cliente, "productos", columnas),
        "No se pudieron leer los productos.",
    )


COLUMNAS_CATALOGO_PUBLICO = "nombre,marca,categoria,imagen_url,activo"
COLUMNAS_CATALOGO_CLIENTE = (
    "id,nombre,marca,categoria,imagen_url,activo,stock_actual,precio_puntero_usd,precio_distro_usd"
)


def cargar_productos_activos(sb: Client, columnas: str) -> list[dict]:
    """Productos activos. activo nulo cuenta como activo, igual que esta_activo."""
    filas = []
    inicio = 0
    tamano = 1000
    while True:
        lote = (
            sb.table("productos")
            .select(columnas)
            .or_("activo.eq.true,activo.is.null")
            .range(inicio, inicio + tamano - 1)
            .execute()
            .data
            or []
        )
        filas.extend(lote)
        if len(lote) < tamano:
            return filas
        inicio += tamano


@st.cache_data(ttl=60, show_spinner=False)
def leer_catalogo_publico() -> list[dict]:
    return cargar_productos_activos(get_supabase(), COLUMNAS_CATALOGO_PUBLICO)


@st.cache_data(ttl=60, show_spinner=False)
def leer_catalogo_cliente() -> list[dict]:
    return cargar_todo(get_supabase(), "productos", COLUMNAS_CATALOGO_CLIENTE)


def _columna_ausente(exc: Exception, columna: str) -> bool:
    texto = texto_error(exc).lower()
    return columna in texto and ("42703" in texto or "column" in texto or "schema cache" in texto)


COLUMNAS_CLIENTES = "id,nombre,email,es_distribuidor,porcentaje_ganancia,activo,tiene_ficha,created_at"


def _columnas_sin(columnas: str, ausente: str) -> str:
    return ",".join(parte.strip() for parte in columnas.split(",") if parte.strip() and parte.strip() != ausente)


def _con_columnas_cliente(columnas: str, accion):
    """Ejecuta la lectura. Si tiene_ficha o email todavía no existen, reintenta sin esa columna."""
    actual = columnas
    while True:
        try:
            return accion(actual)
        except Exception as exc:
            presentes = {parte.strip() for parte in actual.split(",")}
            faltante = next(
                (
                    columna
                    for columna in ("tiene_ficha", "email")
                    if columna in presentes and _columna_ausente(exc, columna)
                ),
                None,
            )
            if faltante is None:
                raise
            actual = _columnas_sin(actual, faltante)


def _aviso_columna_cliente(columna: str) -> str:
    if columna == "email":
        return (
            "Se guardó el cliente, pero el email no quedó en la base. "
            "Falta la columna email en Supabase."
        )
    return (
        "Se guardó el cliente, pero la ficha no quedó en la base. "
        "Falta la columna tiene_ficha en Supabase."
    )


def _escribir_cliente(sb: Client, datos: dict, cliente_id: int | None):
    payload = dict(datos)
    avisos: list[str] = []
    while True:
        try:
            if cliente_id is None:
                return sb.table("clientes").insert(payload).execute(), avisos
            sb.table("clientes").update(payload).eq("id", int(cliente_id)).execute()
            return None, avisos
        except Exception as exc:
            faltante = next(
                (
                    columna
                    for columna in ("email", "tiene_ficha")
                    if columna in payload and _columna_ausente(exc, columna)
                ),
                None,
            )
            if faltante is None:
                raise
            payload.pop(faltante, None)
            avisos.append(_aviso_columna_cliente(faltante))


def leer_cliente_por_id(sb: Client, cliente_id: int) -> dict | None:
    filas = _con_columnas_cliente(
        "id,nombre,es_distribuidor,porcentaje_ganancia,activo,tiene_ficha",
        lambda columnas: sb.table("clientes").select(columnas).eq("id", int(cliente_id)).limit(1).execute().data
        or [],
    )
    if not filas:
        return None
    return filas[0]


def leer_cliente_por_email(sb: Client, email: str) -> dict | None:
    patron = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    try:
        filas = _con_columnas_cliente(
            "id,nombre,es_distribuidor,porcentaje_ganancia,activo,email,tiene_ficha",
            lambda columnas: sb.table("clientes").select(columnas).ilike("email", patron).limit(2).execute().data
            or [],
        )
    except Exception as exc:
        if _columna_ausente(exc, "email"):
            return None
        raise
    activos = [fila for fila in filas if esta_activo(fila)]
    if not activos:
        return None
    return activos[0]


def normalizar_email(email: str) -> tuple[str | None, str | None]:
    texto = email.strip().lower()
    if not texto:
        return None, None
    partes = texto.split("@")
    if len(partes) != 2 or not partes[0] or "." not in partes[1] or any(c.isspace() for c in texto):
        return None, "El email de acceso no es válido."
    return texto, None


def leer_fletes(sb: Client):
    return consultar(sb, lambda cliente: cargar_todo(cliente, "tipos_flete"), "No se pudieron leer los fletes.")


def leer_pedidos_cliente(sb: Client, cliente_id: int):
    return consultar(
        sb,
        lambda conexion: conexion.table("pedidos").select("*").eq("cliente_id", int(cliente_id)).execute().data,
        "No se pudieron leer los pedidos.",
    )


def leer_pagos_cliente(sb: Client, cliente_id: int):
    return consultar(
        sb,
        lambda conexion: conexion.table("pagos").select("*").eq("cliente_id", int(cliente_id)).execute().data,
        "No se pudieron leer los pagos.",
    )


def leer_detalles_pedidos(sb: Client, pedido_ids: list[int]):
    return consultar(
        sb,
        lambda conexion: conexion.table("detalle_pedidos")
        .select("pedido_id,cantidad,producto_id")
        .in_("pedido_id", pedido_ids)
        .execute()
        .data,
        "No se pudo leer el detalle de los pedidos.",
    )


def resumen_global(sb: Client) -> tuple[float, float, float] | None:
    """Vendido neto a rendir, cobrado y deuda de las fichas.

    Vendido y cobrado suman toda la base. La deuda global solo incluye
    clientes con ficha: el saldo que está en la calle.
    """
    pedidos = consultar(
        sb,
        lambda cliente: cargar_todo(
            cliente,
            "pedidos",
            "cliente_id,total_venta_usd,costo_total_usd,ganancia_bruta_usd,ganancia_real_usd",
        ),
        "No se pudo calcular la deuda global.",
    )
    pagos = consultar(
        sb,
        lambda cliente: cargar_todo(cliente, "pagos", "cliente_id,monto_usd_descontado"),
        "No se pudieron leer los pagos acumulados.",
    )
    clientes = consultar(
        sb,
        lambda cliente: _con_columnas_cliente(
            "id,nombre,es_distribuidor,porcentaje_ganancia,tiene_ficha",
            lambda columnas: cargar_todo(cliente, "clientes", columnas),
        ),
        "No se pudieron leer los clientes del resumen.",
    )
    if pedidos is None or pagos is None or clientes is None:
        return None
    por_id = {int(item["id"]): item for item in clientes}
    vendido = round(
        sum(
            cargo_cuenta(
                pedido,
                por_id.get(int(pedido["cliente_id"])) if pedido.get("cliente_id") is not None else None,
            )
            for pedido in pedidos
        ),
        2,
    )
    cobrado = round(sum(float(item.get("monto_usd_descontado") or 0) for item in pagos), 2)
    return vendido, cobrado, deuda_de_fichas(pedidos, pagos, por_id)


def deuda_de_fichas(pedidos: list, pagos: list, por_id: dict) -> float:
    """Suma el saldo de cada cliente con ficha, igual que su cuenta corriente."""
    cargos: dict[int, float] = {}
    abonos: dict[int, float] = {}
    for pedido in pedidos:
        if pedido.get("cliente_id") is None:
            continue
        cliente_id = int(pedido["cliente_id"])
        cliente = por_id.get(cliente_id)
        if not tiene_ficha(cliente):
            continue
        cargos[cliente_id] = cargos.get(cliente_id, 0.0) + cargo_cuenta(pedido, cliente)
    for pago in pagos:
        if pago.get("cliente_id") is None:
            continue
        cliente_id = int(pago["cliente_id"])
        if not tiene_ficha(por_id.get(cliente_id)):
            continue
        abonos[cliente_id] = abonos.get(cliente_id, 0.0) + float(pago.get("monto_usd_descontado") or 0)
    saldo = 0.0
    for cliente_id in cargos.keys() | abonos.keys():
        saldo += round(round(cargos.get(cliente_id, 0.0), 2) - abonos.get(cliente_id, 0.0), 2)
    return round(saldo, 2)


def leer_cartera(sb: Client):
    """Pedidos y pagos para la antigüedad de deuda y los reportes de cuenta."""
    pedidos = consultar(
        sb,
        lambda cliente: cargar_todo(
            cliente,
            "pedidos",
            "id,cliente_id,fecha,detalle,total_venta_usd,costo_total_usd,ganancia_bruta_usd,ganancia_real_usd",
        ),
        "No se pudo leer la cartera de pedidos.",
    )
    pagos = consultar(sb, _pagos_cartera, "No se pudieron leer los pagos de la cartera.")
    if pedidos is None or pagos is None:
        return None
    return pedidos, pagos


def _pagos_cartera(sb: Client):
    columnas = "id,cliente_id,fecha,moneda,monto_original,cotizacion,monto_usd_descontado,observaciones"
    try:
        return cargar_todo(sb, "pagos", f"{columnas},pedido_id")
    except Exception as exc:
        if "pedido_id" not in texto_error(exc):
            raise
        return cargar_todo(sb, "pagos", columnas)


def _error_cliente(exc: Exception, accion: str) -> str:
    if es_duplicado(exc):
        if "email" in texto_error(exc).lower():
            return "Ya hay un cliente con ese email."
        return "Ya existe un cliente con ese nombre."
    return f"No se pudo {accion} el cliente. {texto_error(exc)}"


def insertar_cliente(
    sb: Client,
    nombre: str,
    es_distribuidor: bool,
    email: str | None = None,
    tiene_ficha: bool = False,
) -> tuple[int | None, str | None]:
    datos = datos_cliente(nombre, es_distribuidor)
    datos["tiene_ficha"] = bool(tiene_ficha)
    if not datos["nombre"]:
        return None, "El nombre del cliente es obligatorio."
    if email is not None:
        limpio, error_email = normalizar_email(email)
        if error_email:
            return None, error_email
        datos["email"] = limpio
    try:
        respuesta, avisos = _escribir_cliente(sb, datos, None)
    except Exception as exc:
        return None, _error_cliente(exc, "guardar")
    if not respuesta.data:
        return None, "Supabase no devolvió el cliente creado."
    return int(respuesta.data[0]["id"]), " ".join(avisos) or None


def actualizar_cliente(
    sb: Client,
    cliente_id: int,
    nombre: str,
    es_distribuidor: bool,
    activo: bool | None = None,
    email: str | None = None,
    tiene_ficha: bool | None = None,
) -> str | None:
    datos = datos_cliente(nombre, es_distribuidor)
    if activo is not None:
        datos["activo"] = bool(activo)
    if tiene_ficha is not None:
        datos["tiene_ficha"] = bool(tiene_ficha)
    if not datos["nombre"]:
        return "El nombre del cliente es obligatorio."
    if email is not None:
        limpio, error_email = normalizar_email(email)
        if error_email:
            return error_email
        datos["email"] = limpio
    try:
        _respuesta, avisos = _escribir_cliente(sb, datos, int(cliente_id))
    except Exception as exc:
        return _error_cliente(exc, "actualizar")
    return " ".join(avisos) or None


def eliminar_cliente(sb: Client, cliente_id: int) -> tuple[str, str] | None:
    try:
        if cliente_tiene_movimientos(sb, int(cliente_id)):
            sb.table("clientes").update({"activo": False}).eq("id", int(cliente_id)).execute()
            return "success", "Cliente desactivado para preservar los reportes históricos."
        sb.table("clientes").delete().eq("id", int(cliente_id)).execute()
    except Exception as exc:
        if es_en_uso(exc):
            try:
                sb.table("clientes").update({"activo": False}).eq("id", int(cliente_id)).execute()
            except Exception as segundo:
                return "error", f"No se pudo desactivar el cliente. {texto_error(segundo)}"
            return "success", "Cliente desactivado para preservar los reportes históricos."
        return "error", f"No se pudo eliminar el cliente. {texto_error(exc)}"
    return None


def cliente_tiene_movimientos(sb: Client, cliente_id: int) -> bool:
    pedidos = (
        sb.table("pedidos").select("id").eq("cliente_id", int(cliente_id)).limit(1).execute().data or []
    )
    if pedidos:
        return True
    pagos = sb.table("pagos").select("id").eq("cliente_id", int(cliente_id)).limit(1).execute().data or []
    return bool(pagos)


BUCKET_PRODUCTOS = "productos"
_TIPOS_IMAGEN = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def tipo_imagen(nombre: str, tipo: str) -> tuple[str, str] | None:
    limpio = (tipo or "").split(";")[0].strip().lower()
    if limpio == "image/jpg":
        limpio = "image/jpeg"
    if limpio in _TIPOS_IMAGEN:
        return limpio, _TIPOS_IMAGEN[limpio]
    archivo = (nombre or "").lower()
    if archivo.endswith(".png"):
        return "image/png", ".png"
    if archivo.endswith(".jpeg") or archivo.endswith(".jpg"):
        return "image/jpeg", ".jpg"
    if archivo.endswith(".webp"):
        return "image/webp", ".webp"
    return None


def subir_imagen_producto(sb: Client, archivo) -> str:
    """Sube una imagen al bucket público y devuelve su URL."""
    tipo = tipo_imagen(getattr(archivo, "name", ""), getattr(archivo, "type", "") or "")
    if tipo is None:
        raise ValueError("La imagen tiene que ser png, jpg o webp.")
    contenido = archivo.getvalue()
    if not contenido:
        raise ValueError("El archivo de imagen está vacío.")
    mime, extension = tipo
    ruta = f"{uuid.uuid4().hex}{extension}"
    autorizacion = sb.postgrest.headers.get("Authorization")
    if autorizacion:
        sb.storage.session.headers["Authorization"] = str(autorizacion)
        sb.storage._headers["Authorization"] = str(autorizacion)
    sb.storage.from_(BUCKET_PRODUCTOS).upload(
        ruta,
        contenido,
        file_options={"content-type": mime},
    )
    return sb.storage.from_(BUCKET_PRODUCTOS).get_public_url(ruta)


def guardar_producto(sb: Client, datos: dict, producto_id: int | None) -> str | None:
    error = _escribir_producto(sb, datos, producto_id)
    if error is None:
        return None
    opcionales = ("precio_kg", "calcular_costo", "costo_total_usd", "activo", "incompleto")
    if not any(campo in error for campo in opcionales):
        return error
    reducido = {clave: valor for clave, valor in datos.items() if clave not in opcionales}
    error_reducido = _escribir_producto(sb, reducido, producto_id)
    if error_reducido:
        return error_reducido
    if datos.get("calcular_costo") is False:
        return (
            "Se guardó el producto, pero el costo manual no quedó en la base. "
            "Falta la columna costo_total_usd en Supabase."
        )
    return None


def _escribir_producto(sb: Client, datos: dict, producto_id: int | None) -> str | None:
    try:
        if producto_id is None:
            respuesta = sb.table("productos").insert(datos).execute()
        else:
            respuesta = sb.table("productos").update(datos).eq("id", int(producto_id)).execute()
    except Exception as exc:
        return f"No se pudo guardar el producto. {texto_error(exc)}"
    if not respuesta.data:
        return (
            "No se pudo guardar el producto. Supabase no devolvió la fila. "
            "Faltan permisos de escritura: ejecutá 02_fix_seguridad.sql."
        )
    return None


def eliminar_producto(sb: Client, producto_id: int, nombre: str = "") -> tuple[str, str] | None:
    try:
        if producto_tiene_ventas(sb, int(producto_id), nombre):
            sb.table("productos").update({"activo": False}).eq("id", int(producto_id)).execute()
            return "success", "Producto desactivado para preservar los reportes históricos."
        sb.table("productos").delete().eq("id", int(producto_id)).execute()
    except Exception as exc:
        if es_en_uso(exc):
            try:
                sb.table("productos").update({"activo": False}).eq("id", int(producto_id)).execute()
            except Exception as segundo:
                return "error", f"No se pudo desactivar el producto. {texto_error(segundo)}"
            return "success", "Producto desactivado para preservar los reportes históricos."
        return "error", f"No se pudo eliminar el producto. {texto_error(exc)}"
    return None


def producto_tiene_ventas(sb: Client, producto_id: int, nombre: str = "") -> bool:
    """Hay venta si el producto está en el detalle o nombrado en un pedido histórico."""
    lineas = (
        sb.table("detalle_pedidos")
        .select("id")
        .eq("producto_id", int(producto_id))
        .limit(1)
        .execute()
        .data
        or []
    )
    if lineas:
        return True
    texto = " ".join(str(nombre or "").split())
    if not texto:
        return False
    escapado = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    mencionados = (
        sb.table("pedidos").select("id").ilike("detalle", f"%{escapado}%").limit(1).execute().data or []
    )
    return bool(mencionados)


def esta_activo(fila: dict | None) -> bool:
    if not fila:
        return False
    return fila.get("activo") is not False


def actualizar_flete(sb: Client, flete_id: int, nombre: str, costo_usd_kg: float) -> None:
    respuesta = sb.table("tipos_flete").update(
        {
            "nombre": nombre,
            "costo_usd_kg": round(float(costo_usd_kg), 2),
        }
    ).eq("id", int(flete_id)).execute()
    if not respuesta.data:
        raise RuntimeError("No se pudo actualizar el flete. Revisá los permisos en Supabase.")


def insertar_flete(sb: Client, nombre: str, costo_usd_kg: float) -> None:
    respuesta = sb.table("tipos_flete").insert(
        {
            "nombre": nombre,
            "costo_usd_kg": round(float(costo_usd_kg), 2),
        }
    ).execute()
    if not respuesta.data:
        raise RuntimeError("No se pudo guardar el flete. Revisá los permisos en Supabase.")


def eliminar_flete(sb: Client, flete_id: int) -> str | None:
    try:
        usados = (
            sb.table("productos").select("id").eq("flete_id", int(flete_id)).limit(1).execute().data or []
        )
    except Exception as exc:
        if "flete_id" not in texto_error(exc).lower():
            return f"No se pudo eliminar el flete. {texto_error(exc)}"
        usados = []
    if usados:
        return "Hay productos que usan este flete. Cambiá su precio por kilo antes de eliminarlo."
    try:
        respuesta = sb.table("tipos_flete").delete().eq("id", int(flete_id)).execute()
    except Exception as exc:
        if es_en_uso(exc):
            return "Hay productos que usan este flete. Cambiá su precio por kilo antes de eliminarlo."
        return f"No se pudo eliminar el flete. {texto_error(exc)}"
    if not respuesta.data:
        return "No se pudo eliminar el flete. Revisá los permisos en Supabase."
    return None


def _nombre_catalogo(nombre: str) -> str:
    return " ".join(str(nombre or "").split())


def _patron_igual(nombre: str) -> str:
    return nombre.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tabla_catalogo_ausente(exc: Exception) -> bool:
    texto = texto_error(exc).lower()
    return any(marca in texto for marca in ("pgrst205", "does not exist", "42p01", "schema cache"))


def leer_marcas(sb: Client):
    return consultar(sb, lambda cliente: cargar_todo(cliente, "marcas"), "No se pudieron leer las marcas.")


def leer_categorias(sb: Client):
    return consultar(sb, lambda cliente: cargar_todo(cliente, "categorias"), "No se pudieron leer las categorías.")


def _nombre_ocupado(sb: Client, tabla: str, nombre: str, propio_id: int | None) -> bool:
    filas = sb.table(tabla).select("id,nombre").ilike("nombre", _patron_igual(nombre)).execute().data or []
    clave = nombre.casefold()
    for fila in filas:
        if propio_id is not None and int(fila["id"]) == int(propio_id):
            continue
        if _nombre_catalogo(fila.get("nombre")).casefold() == clave:
            return True
    return False


def _insertar_catalogo(sb: Client, tabla: str, etiqueta: str, nombre: str) -> str | None:
    limpio = _nombre_catalogo(nombre)
    if not limpio:
        return f"El nombre de la {etiqueta} es obligatorio."
    try:
        if _nombre_ocupado(sb, tabla, limpio, None):
            return f"Ya existe una {etiqueta} con ese nombre."
        respuesta = sb.table(tabla).insert({"nombre": limpio}).execute()
    except Exception as exc:
        if es_duplicado(exc):
            return f"Ya existe una {etiqueta} con ese nombre."
        return f"No se pudo guardar la {etiqueta}. {texto_error(exc)}"
    if not respuesta.data:
        return f"No se pudo guardar la {etiqueta}. Revisá los permisos en Supabase."
    return None


def _actualizar_catalogo(sb: Client, tabla: str, columna: str, etiqueta: str, item_id: int, nombre: str) -> str | None:
    limpio = _nombre_catalogo(nombre)
    if not limpio:
        return f"El nombre de la {etiqueta} es obligatorio."
    try:
        actuales = sb.table(tabla).select("nombre").eq("id", int(item_id)).limit(1).execute().data or []
        if not actuales:
            return f"No se encontró la {etiqueta}."
        anterior = _nombre_catalogo(actuales[0].get("nombre"))
        if anterior.casefold() == limpio.casefold() and anterior == limpio:
            return None
        if _nombre_ocupado(sb, tabla, limpio, int(item_id)):
            return f"Ya existe una {etiqueta} con ese nombre."
        respuesta = sb.table(tabla).update({"nombre": limpio}).eq("id", int(item_id)).execute()
        if not respuesta.data:
            return f"No se pudo actualizar la {etiqueta}. Revisá los permisos en Supabase."
        if anterior != limpio:
            sb.table("productos").update({columna: limpio}).eq(columna, anterior).execute()
    except Exception as exc:
        if es_duplicado(exc):
            return f"Ya existe una {etiqueta} con ese nombre."
        return f"No se pudo actualizar la {etiqueta}. {texto_error(exc)}"
    return None


def _eliminar_catalogo(sb: Client, tabla: str, columna: str, etiqueta: str, item_id: int) -> str | None:
    try:
        actuales = sb.table(tabla).select("nombre").eq("id", int(item_id)).limit(1).execute().data or []
        if not actuales:
            return f"No se encontró la {etiqueta}."
        nombre = _nombre_catalogo(actuales[0].get("nombre"))
        usados = sb.table("productos").select("id").eq(columna, nombre).limit(1).execute().data or []
        if usados:
            return f"Hay productos con esta {etiqueta}. Cambiales el valor antes de eliminarla."
        respuesta = sb.table(tabla).delete().eq("id", int(item_id)).execute()
    except Exception as exc:
        return f"No se pudo eliminar la {etiqueta}. {texto_error(exc)}"
    if not respuesta.data:
        return f"No se pudo eliminar la {etiqueta}. Revisá los permisos en Supabase."
    return None


def insertar_marca(sb: Client, nombre: str) -> str | None:
    return _insertar_catalogo(sb, "marcas", "marca", nombre)


def actualizar_marca(sb: Client, marca_id: int, nombre: str) -> str | None:
    return _actualizar_catalogo(sb, "marcas", "marca", "marca", marca_id, nombre)


def eliminar_marca(sb: Client, marca_id: int) -> str | None:
    return _eliminar_catalogo(sb, "marcas", "marca", "marca", marca_id)


def insertar_categoria(sb: Client, nombre: str) -> str | None:
    return _insertar_catalogo(sb, "categorias", "categoría", nombre)


def actualizar_categoria(sb: Client, categoria_id: int, nombre: str) -> str | None:
    return _actualizar_catalogo(sb, "categorias", "categoria", "categoría", categoria_id, nombre)


def eliminar_categoria(sb: Client, categoria_id: int) -> str | None:
    return _eliminar_catalogo(sb, "categorias", "categoria", "categoría", categoria_id)


def leer_conceptos_gasto(sb: Client):
    filas = consultar(
        sb,
        lambda cliente: cargar_todo(cliente, "conceptos_gasto"),
        "No se pudieron leer los conceptos de gasto.",
    )
    if filas is None:
        return None
    return sorted(filas, key=lambda item: str(item.get("nombre") or "").casefold())


def insertar_concepto_gasto(sb: Client, nombre: str) -> str | None:
    limpio = _nombre_catalogo(nombre)
    if not limpio:
        return "El nombre del concepto es obligatorio."
    try:
        if _nombre_ocupado(sb, "conceptos_gasto", limpio, None):
            return "Ya existe un concepto con ese nombre."
        respuesta = sb.table("conceptos_gasto").insert({"nombre": limpio}).execute()
    except Exception as exc:
        if es_duplicado(exc):
            return "Ya existe un concepto con ese nombre."
        if _tabla_catalogo_ausente(exc):
            return "Falta la tabla conceptos_gasto. Ejecutá 06_conceptos_gasto.sql en Supabase."
        return f"No se pudo guardar el concepto. {texto_error(exc)}"
    if not respuesta.data:
        return "No se pudo guardar el concepto. Revisá los permisos en Supabase."
    return None


def eliminar_concepto_gasto(sb: Client, concepto_id: int) -> str | None:
    try:
        respuesta = sb.table("conceptos_gasto").delete().eq("id", int(concepto_id)).execute()
    except Exception as exc:
        if _tabla_catalogo_ausente(exc):
            return "Falta la tabla conceptos_gasto. Ejecutá 06_conceptos_gasto.sql en Supabase."
        return f"No se pudo eliminar el concepto. {texto_error(exc)}"
    if not respuesta.data:
        return "No se pudo eliminar el concepto. Revisá los permisos en Supabase."
    return None


def asegurar_en_catalogo(sb: Client, tabla: str, nombre: str) -> None:
    """Registra el nombre si la tabla existe. No frena una importación si todavía no está creada."""
    limpio = _nombre_catalogo(nombre)
    if not limpio:
        return
    try:
        if _nombre_ocupado(sb, tabla, limpio, None):
            return
        sb.table(tabla).insert({"nombre": limpio}).execute()
    except Exception as exc:
        if es_duplicado(exc) or _tabla_catalogo_ausente(exc):
            return
        return


ART = timezone(timedelta(hours=-3))


def _dia_gasto(valor) -> date | None:
    momento = parse_fecha(valor)
    if momento.year <= 1:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ART)
    return momento.astimezone(ART).date()


def leer_gastos(sb: Client, fecha_desde: date | None = None, fecha_hasta: date | None = None):
    filas = consultar(
        sb,
        lambda cliente: cargar_todo(cliente, "gastos_operativos"),
        "No se pudieron leer los gastos operativos.",
    )
    if filas is None or fecha_desde is None or fecha_hasta is None:
        return filas
    return [
        fila
        for fila in filas
        if (dia := _dia_gasto(fila.get("fecha"))) is not None and fecha_desde <= dia <= fecha_hasta
    ]


def registrar_gasto(sb: Client, payload: dict) -> str | None:
    datos = dict(payload)
    datos["concepto"] = " ".join(str(datos.get("concepto") or "").split())
    if not datos["concepto"]:
        return "El concepto es obligatorio."
    if float(datos.get("monto_usd") or 0) <= 0:
        return "El monto en dólares tiene que ser mayor a cero."
    try:
        respuesta = sb.table("gastos_operativos").insert(datos).execute()
    except Exception as exc:
        return f"No se pudo registrar el gasto. {texto_error(exc)}"
    if not respuesta.data:
        return "No se pudo registrar el gasto. Revisá los permisos en Supabase."
    return None


def eliminar_gasto(sb: Client, gasto_id: int) -> str | None:
    try:
        respuesta = sb.table("gastos_operativos").delete().eq("id", int(gasto_id)).execute()
    except Exception as exc:
        return f"No se pudo eliminar el gasto. {texto_error(exc)}"
    if not respuesta.data:
        return "No se pudo eliminar el gasto. Revisá los permisos en Supabase."
    return None


def registrar_pago(sb: Client, payload: dict) -> str | None:
    try:
        sb.table("pagos").insert(payload).execute()
    except Exception as exc:
        if payload.get("pedido_id") is None or "pedido_id" not in texto_error(exc):
            return f"No se pudo registrar el pago. {texto_error(exc)}"
        reducido = {clave: valor for clave, valor in payload.items() if clave != "pedido_id"}
        try:
            sb.table("pagos").insert(reducido).execute()
        except Exception as segundo:
            return f"No se pudo registrar el pago. {texto_error(segundo)}"
        return (
            "Se registró el pago en la cuenta, pero no quedó vinculado al pedido. "
            "Falta la columna pedido_id en pagos."
        )
    return None


def crear_pedido(
    sb: Client,
    cliente_id: int,
    total_venta: float,
    costo_total: float,
    ganancia_bruta: float,
    ganancia_real: float,
    lineas: list,
    notas: str = "",
) -> tuple[str | None, list[str]]:
    pedido_id = None
    try:
        descripcion = ", ".join(
            f"{int(linea['cantidad'])} x {linea['producto']['nombre']}" for linea in lineas
        )
        nota = " ".join(str(notas or "").split())
        payload = {
            "cliente_id": int(cliente_id),
            "total_venta_usd": total_venta,
            "costo_total_usd": costo_total,
            "ganancia_bruta_usd": ganancia_bruta,
            "ganancia_real_usd": ganancia_real,
            "detalle": descripcion,
            "observaciones": nota or None,
        }
        try:
            respuesta = sb.table("pedidos").insert(payload).execute()
        except Exception as exc:
            if "observaciones" not in texto_error(exc):
                raise
            payload.pop("observaciones", None)
            if nota:
                payload["detalle"] = f"{descripcion} | {nota}" if descripcion else nota
            respuesta = sb.table("pedidos").insert(payload).execute()
        if not respuesta.data:
            raise RuntimeError("Supabase no devolvió el pedido creado.")
        pedido_id = int(respuesta.data[0]["id"])
        sb.table("detalle_pedidos").insert(
            [
                {
                    "pedido_id": pedido_id,
                    "producto_id": int(linea["producto"]["id"]),
                    "cantidad": int(linea["cantidad"]),
                    "precio_unitario_cobrado": round(linea["precio"], 2),
                    "costo_unitario_historico": round(linea["costo"], 2),
                }
                for linea in lineas
            ]
        ).execute()
    except Exception as exc:
        if pedido_id is not None:
            try:
                sb.table("pedidos").delete().eq("id", pedido_id).execute()
            except Exception:
                return (
                    f"No se pudo completar el pedido {pedido_id} y tampoco se pudo anular. {texto_error(exc)}",
                    [],
                )
        return f"No se pudo guardar el pedido. {texto_error(exc)}", []

    errores_stock = []
    for linea in lineas:
        producto = linea["producto"]
        nuevo_stock = int(producto.get("stock_actual") or 0) - int(linea["cantidad"])
        try:
            respuesta = (
                sb.table("productos")
                .update({"stock_actual": nuevo_stock})
                .eq("id", int(producto["id"]))
                .execute()
            )
            if not respuesta.data:
                errores_stock.append(producto["nombre"])
        except Exception:
            errores_stock.append(producto["nombre"])
    return None, errores_stock
