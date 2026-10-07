import pandas as pd
import streamlit as st
from supabase import Client

from database import (
    actualizar_categoria,
    actualizar_flete,
    actualizar_marca,
    eliminar_categoria,
    eliminar_concepto_gasto,
    eliminar_flete,
    eliminar_marca,
    insertar_categoria,
    insertar_concepto_gasto,
    insertar_flete,
    insertar_marca,
    leer_categorias,
    leer_conceptos_gasto,
    leer_fletes,
    leer_marcas,
    texto_error,
)
from ui import avisar


def gestion_fletes(sb: Client, fletes: list) -> None:
    st.caption("Costo de envío en USD por kilo. Se usa al calcular el costo de cada producto.")
    columna_tarifas, columna_alta = st.columns([1.7, 1], vertical_alignment="top")

    with columna_tarifas:
        if not fletes:
            st.warning("No hay tipos de flete cargados.")
        else:
            editor = pd.DataFrame(fletes)[["id", "nombre", "costo_usd_kg"]]
            version = st.session_state.get("flete_version", 0)
            editado = st.data_editor(
                editor,
                hide_index=True,
                num_rows="fixed",
                width="stretch",
                height=min(320, 56 + 36 * len(fletes)),
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
                    st.cache_data.clear()
                    avisar(
                        "success",
                        "Tarifas actualizadas. El costo total se recalcula con la tarifa nueva y el FOB no cambia.",
                    )

    with columna_alta:
        with st.container(border=True):
            with st.form("nuevo_flete", clear_on_submit=True):
                st.markdown("**Nuevo tipo de flete**")
                nombre_nuevo = st.text_input("Nombre del flete")
                tarifa_nueva = st.number_input("Tarifa USD por kg", min_value=0.0, step=0.01)
                crear_flete = st.form_submit_button("Agregar tipo de flete", width="stretch")
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
                    st.cache_data.clear()
                    avisar("success", f"Tipo de flete {nombre_nuevo.strip()} agregado.")
        if fletes:
            st.markdown("**Eliminar flete**")
            opciones_borrar = {str(item["nombre"]): int(item["id"]) for item in fletes}
            elegido = st.selectbox("Flete a eliminar", list(opciones_borrar), key="flete_a_eliminar")
            if st.button("Eliminar flete", key="btn_eliminar_flete"):
                error = eliminar_flete(sb, opciones_borrar[elegido])
                if error:
                    st.error(error)
                else:
                    st.cache_data.clear()
                    avisar("success", f"Flete {elegido} eliminado.")


def gestion_catalogo(
    sb: Client,
    etiqueta: str,
    singular: str,
    registros: list,
    insertar,
    actualizar,
    eliminar,
    clave: str,
) -> None:
    st.caption("Estos nombres se eligen al cargar un producto, así no quedan diferencias de tipeo.")
    columna_lista, columna_alta = st.columns([1.7, 1], vertical_alignment="top")
    ordenados = sorted(registros, key=lambda item: str(item.get("nombre") or "").lower())
    with columna_lista:
        if not ordenados:
            st.warning(f"Todavía no hay {etiqueta.lower()}.")
        else:
            editor = pd.DataFrame(ordenados)[["id", "nombre"]]
            version = st.session_state.get(f"{clave}_version", 0)
            editado = st.data_editor(
                editor,
                hide_index=True,
                num_rows="fixed",
                width="stretch",
                height=min(320, 56 + 36 * len(ordenados)),
                key=f"editor_{clave}_{version}",
                column_order=["nombre"],
                column_config={
                    "nombre": st.column_config.TextColumn(etiqueta, required=True),
                },
            )
            if st.button(f"Guardar {etiqueta.lower()}", type="primary", key=f"guardar_{clave}"):
                for indice, (_, fila) in enumerate(editado.iterrows()):
                    error = actualizar(sb, int(ordenados[indice]["id"]), str(fila["nombre"]))
                    if error:
                        st.error(error)
                        return
                st.session_state[f"{clave}_version"] = version + 1
                st.cache_data.clear()
                avisar("success", f"{etiqueta} actualizadas.")
    with columna_alta:
        with st.container(border=True):
            with st.form(f"alta_{clave}", clear_on_submit=True):
                st.markdown(f"**Nueva {singular}**")
                nombre_nuevo = st.text_input("Nombre")
                crear = st.form_submit_button("Agregar", width="stretch")
            if crear:
                error = insertar(sb, nombre_nuevo)
                if error:
                    st.error(error)
                else:
                    st.cache_data.clear()
                    avisar("success", f"{singular.capitalize()} agregada.")
            if ordenados:
                st.markdown(f"**Eliminar {singular}**")
                opciones = {f"{item['nombre']}": int(item["id"]) for item in ordenados}
                elegido = st.selectbox(singular.capitalize(), list(opciones), key=f"eliminar_sel_{clave}")
                if st.button("Eliminar", key=f"eliminar_{clave}"):
                    error = eliminar(sb, opciones[elegido])
                    if error:
                        st.error(error)
                    else:
                        st.cache_data.clear()
                        avisar("success", f"{elegido} eliminada.")


def gestion_conceptos(sb: Client, conceptos: list) -> None:
    st.caption("Estos nombres se eligen al registrar un gasto.")
    columna_lista, columna_alta = st.columns([1.7, 1], vertical_alignment="top")
    ordenados = sorted(conceptos, key=lambda item: str(item.get("nombre") or "").casefold())
    with columna_lista:
        if not ordenados:
            st.info("Todavía no hay conceptos de gasto.")
        else:
            st.dataframe(
                pd.DataFrame({"Concepto": [item["nombre"] for item in ordenados]}),
                hide_index=True,
                width="stretch",
                height=min(320, 56 + 36 * len(ordenados)),
            )
    with columna_alta:
        with st.container(border=True):
            with st.form("alta_concepto_gasto", clear_on_submit=True):
                st.markdown("**Nuevo concepto**")
                nombre_nuevo = st.text_input("Nombre")
                crear = st.form_submit_button("Agregar", width="stretch")
            if crear:
                error = insertar_concepto_gasto(sb, nombre_nuevo)
                if error:
                    st.error(error)
                else:
                    st.cache_data.clear()
                    avisar("success", f"Concepto {nombre_nuevo.strip()} agregado.")
            if ordenados:
                st.markdown("**Eliminar concepto**")
                opciones = {str(item["nombre"]): str(item["id"]) for item in ordenados}
                elegido = st.selectbox("Concepto", list(opciones), key="eliminar_sel_concepto_gasto")
                if st.button("Eliminar", key="eliminar_concepto_gasto"):
                    error = eliminar_concepto_gasto(sb, opciones[elegido])
                    if error:
                        st.error(error)
                    else:
                        st.cache_data.clear()
                        avisar("success", f"Concepto {elegido} eliminado.")


def pagina_configuracion(sb: Client) -> None:
    fletes = leer_fletes(sb)
    marcas = leer_marcas(sb)
    categorias = leer_categorias(sb)
    conceptos = leer_conceptos_gasto(sb)
    tab_fletes, tab_marcas, tab_categorias, tab_conceptos = st.tabs(
        ["Fletes", "Marcas", "Categorías", "Conceptos de gasto"]
    )
    with tab_fletes:
        if fletes is None:
            st.warning("No se pudieron leer los fletes.")
        else:
            gestion_fletes(sb, fletes)
    with tab_marcas:
        if marcas is None:
            st.warning("No se pudieron leer las marcas. Ejecutá 03_abm_marcas_categorias.sql en Supabase.")
        else:
            gestion_catalogo(
                sb,
                "Marcas",
                "marca",
                marcas,
                insertar_marca,
                actualizar_marca,
                eliminar_marca,
                "marcas",
            )
    with tab_categorias:
        if categorias is None:
            st.warning("No se pudieron leer las categorías. Ejecutá 03_abm_marcas_categorias.sql en Supabase.")
        else:
            gestion_catalogo(
                sb,
                "Categorías",
                "categoría",
                categorias,
                insertar_categoria,
                actualizar_categoria,
                eliminar_categoria,
                "categorias",
            )
    with tab_conceptos:
        if conceptos is None:
            st.warning("No se pudieron leer los conceptos. Ejecutá 06_conceptos_gasto.sql en Supabase.")
        else:
            gestion_conceptos(sb, conceptos)
