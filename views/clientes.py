import pandas as pd
import streamlit as st
from supabase import Client

from auth import generar_acceso_b2b
from database import (
    actualizar_cliente,
    datos_cliente,
    eliminar_cliente,
    esta_activo,
    insertar_cliente,
    leer_clientes,
    normalizar_email,
)
from ui import avisar, checkbox_tiene_ficha, estilo_tipo_cliente, fila_click, mostrar_kpis, sembrar


def _mostrar_acceso(sufijo: str) -> None:
    datos = st.session_state.get(f"acceso_b2b_{sufijo}")
    if not datos:
        return
    st.success("¡Acceso B2B generado con éxito!")
    st.markdown(f"**Usuario:** `{datos['email']}`")
    st.markdown("**Clave temporal:**")
    st.code(datos["clave"])
    st.caption("Podés copiar esta clave y enviársela por WhatsApp al cliente.")
    if datos.get("aviso"):
        st.warning(datos["aviso"])


def _preparar_cliente(
    sb: Client,
    cliente: dict | None,
    sufijo: str,
    nombre: str,
    email: str,
    es_distribuidor: bool,
    activo: bool,
    tiene_ficha: bool,
) -> tuple[int | None, str | None]:
    existente = int(cliente["id"]) if cliente is not None else st.session_state.get(f"cli_id_{sufijo}")
    if existente is None:
        nuevo_id, error = insertar_cliente(sb, nombre, es_distribuidor, email, tiene_ficha)
        if nuevo_id is not None:
            st.session_state[f"cli_id_{sufijo}"] = nuevo_id
            st.session_state["cliente_venta_pendiente"] = nuevo_id
        return nuevo_id, error
    error = actualizar_cliente(sb, int(existente), nombre, es_distribuidor, activo, email, tiene_ficha)
    return int(existente), error


@st.dialog("Cliente", width="large")
def dialogo_cliente(sb: Client, cliente: dict | None = None) -> None:
    sufijo = "nuevo" if cliente is None else str(int(cliente["id"]))
    clave_nombre = f"cli_nombre_{sufijo}"
    clave_email = f"cli_email_{sufijo}"
    clave_tipo = f"cli_tipo_{sufijo}"
    clave_activo = f"cli_activo_{sufijo}"
    clave_ficha = f"cli_ficha_{sufijo}"
    sembrar(clave_nombre, "" if cliente is None else cliente["nombre"])
    sembrar(clave_email, "" if cliente is None else (cliente.get("email") or ""))
    sembrar(clave_tipo, False if cliente is None else bool(cliente.get("es_distribuidor")))
    sembrar(clave_activo, True if cliente is None else esta_activo(cliente))
    sembrar(clave_ficha, False if cliente is None else bool(cliente.get("tiene_ficha")))
    with st.form(f"form_cliente_{sufijo}", enter_to_submit=False):
        st.text_input("Nombre del cliente", key=clave_nombre)
        columna_email, columna_acceso = st.columns([1.5, 1.3], vertical_alignment="bottom")
        with columna_email:
            st.text_input(
                "Email de acceso",
                key=clave_email,
                placeholder="nombre@correo.com",
                help="Con este email el cliente inicia sesión y ve sus precios.",
            )
        with columna_acceso:
            generar = st.form_submit_button(
                "Generar acceso B2B",
                icon=":material/key:",
                width="stretch",
            )
        st.checkbox(
            "¿Es distribuidor?",
            key=clave_tipo,
            help="Si está marcado, la ganancia real es el 50% del margen. Si no, es el 100%.",
        )
        checkbox_tiene_ficha(clave_ficha)
        if cliente is not None:
            st.checkbox("Activo", key=clave_activo)
        guardar = st.form_submit_button("Guardar", type="primary")
    nombre = st.session_state[clave_nombre]
    email = st.session_state[clave_email]
    es_distribuidor = bool(st.session_state[clave_tipo])
    activo = True if cliente is None else bool(st.session_state[clave_activo])
    con_ficha = bool(st.session_state[clave_ficha])
    if generar:
        limpio, error_email = normalizar_email(email)
        if error_email or not limpio:
            st.warning(error_email or "Cargá el email de acceso antes de generar la clave.")
        else:
            cliente_id, error = _preparar_cliente(
                sb, cliente, sufijo, nombre, email, es_distribuidor, activo, con_ficha
            )
            if cliente_id is None:
                st.warning(error or "No se pudo guardar el cliente.")
            elif error and not error.startswith("Se guardó"):
                st.warning(error)
            else:
                if not esta_activo({"activo": activo}):
                    st.warning("El cliente está inactivo y no va a poder entrar hasta que lo actives.")
                try:
                    correo, clave = generar_acceso_b2b(cliente_id, limpio)
                except ValueError as exc:
                    st.warning(str(exc))
                except Exception:
                    st.error("No se pudo generar el acceso.")
                else:
                    st.session_state[f"acceso_b2b_{sufijo}"] = {
                        "email": correo,
                        "clave": clave,
                        "aviso": error if error and error.startswith("Se guardó") else None,
                    }
    elif guardar:
        cliente_id, error = _preparar_cliente(
            sb, cliente, sufijo, nombre, email, es_distribuidor, activo, con_ficha
        )
        if cliente_id is None:
            st.warning(error or "No se pudo guardar el cliente.")
        elif error and error.startswith("Se guardó"):
            avisar("warning", error)
        elif error:
            st.warning(error)
        elif cliente is None:
            avisar("success", f"Cliente {datos_cliente(nombre, es_distribuidor)['nombre']} registrado.")
        else:
            avisar("success", f"Cliente {datos_cliente(nombre, es_distribuidor)['nombre']} actualizado.")
    _mostrar_acceso(sufijo)


@st.dialog("Eliminar cliente")
def dialogo_borrar_cliente(sb: Client, cliente: dict) -> None:
    st.write(f"¿Eliminar a **{cliente['nombre']}**?")
    st.caption("Si tiene pedidos o pagos, se desactiva y queda en los reportes.")
    if st.button("Eliminar", type="primary", key=f"confirmar_borrar_cliente_{int(cliente['id'])}"):
        resultado = eliminar_cliente(sb, int(cliente["id"]))
        if resultado:
            nivel, texto = resultado
            if nivel == "success":
                avisar("success", texto)
            elif nivel == "warning":
                st.warning(texto)
            else:
                st.error(texto)
            return
        avisar("success", f"Cliente {cliente['nombre']} eliminado.")


def estilo_estado(valor) -> str:
    if valor == "Inactivo":
        return "background-color: #F4F4F5; color: #71717A; font-weight: 600;"
    return ""


def pagina_clientes(sb: Client) -> None:
    clientes = leer_clientes(sb)
    if clientes is None:
        return
    mostrar_inactivos = st.checkbox("Mostrar inactivos", key="cli_inactivos")
    clientes = sorted(clientes, key=lambda item: item["nombre"].lower())
    if not mostrar_inactivos:
        clientes = [cliente for cliente in clientes if esta_activo(cliente)]
    distribuidores = sum(1 for item in clientes if item.get("es_distribuidor"))
    mostrar_kpis(
        [
            ("Clientes", str(len(clientes)), "Registrados"),
            ("Distribuidores", str(distribuidores), "Ganancia al 50%"),
            ("Estándar", str(len(clientes) - distribuidores), "Ganancia al 100%"),
        ]
    )
    columna_nota, columna_alta = st.columns([4, 1], vertical_alignment="bottom")
    with columna_nota:
        st.caption("Distribuidor guarda el 50% de la ganancia. Estándar, el 100%.")
    with columna_alta:
        if st.button("+ Nuevo cliente", type="primary", width="stretch"):
            st.session_state.pop("acceso_b2b_nuevo", None)
            st.session_state.pop("cli_id_nuevo", None)
            dialogo_cliente(sb)
    if not clientes:
        st.warning("Todavía no hay clientes.")
        return

    filas = []
    for cliente in clientes:
        fila = {
            "Nombre": cliente["nombre"],
            "Email": cliente.get("email") or "",
            "Tipo": "Distribuidor" if cliente.get("es_distribuidor") else "Estándar",
            "Ficha": "Sí" if cliente.get("tiene_ficha") else "No",
            "Ver como cliente": "Ver como cliente",
            "Editar": ":material/edit:",
            "Eliminar": ":material/delete:",
        }
        if mostrar_inactivos:
            fila["Estado"] = "Activo" if esta_activo(cliente) else "Inactivo"
        filas.append(fila)
    tabla = pd.DataFrame(filas)
    estilo = tabla.style.map(estilo_tipo_cliente, subset=["Tipo"])
    if mostrar_inactivos and "Estado" in tabla.columns:
        estilo = estilo.map(estilo_estado, subset=["Estado"])
    columnas = {
        "Nombre": st.column_config.TextColumn("Nombre", width="large"),
        "Email": st.column_config.TextColumn("Email", width="medium"),
        "Tipo": st.column_config.TextColumn("Tipo", width="medium"),
        "Ficha": st.column_config.TextColumn("Ficha", width="small"),
        "Ver como cliente": st.column_config.ButtonColumn(
            "Ver como cliente",
            type="secondary",
            width="medium",
            key="cli_ver",
        ),
        "Editar": st.column_config.ButtonColumn("Editar", type="tertiary", width="small", key="cli_editar"),
        "Eliminar": st.column_config.ButtonColumn(
            "Eliminar", type="tertiary", width="small", key="cli_eliminar"
        ),
    }
    if mostrar_inactivos:
        columnas["Estado"] = st.column_config.TextColumn("Estado", width="small")
    st.dataframe(
        estilo,
        hide_index=True,
        width="stretch",
        height="auto" if len(tabla) <= 12 else 520,
        row_height=44,
        column_config=columnas,
        column_order=(
            ["Nombre", "Email", "Tipo", "Ficha", "Estado", "Ver como cliente", "Editar", "Eliminar"]
            if mostrar_inactivos
            else ["Nombre", "Email", "Tipo", "Ficha", "Ver como cliente", "Editar", "Eliminar"]
        ),
    )
    ver = fila_click("cli_ver")
    if ver is not None and 0 <= ver < len(clientes):
        st.session_state.pop("cli_ver", None)
        st.session_state["impersonated_client_id"] = int(clientes[ver]["id"])
        st.rerun()
    editar = fila_click("cli_editar")
    if editar is not None and 0 <= editar < len(clientes):
        dialogo_cliente(sb, clientes[editar])
    borrar = fila_click("cli_eliminar")
    if borrar is not None and 0 <= borrar < len(clientes):
        dialogo_borrar_cliente(sb, clientes[borrar])
