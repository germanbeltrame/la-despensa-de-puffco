import os
import secrets
import time

import streamlit as st
from supabase_auth.errors import AuthApiError, AuthInvalidCredentialsError

from database import (
    cliente_nuevo,
    esta_activo,
    leer_cliente_por_email,
    leer_cliente_por_id,
    normalizar_email,
    texto_error,
)

CLAVE_SESION = "sesion_auth"
ROLES_ADMIN = {"admin", "administrador"}
ADMINES_MAESTROS = (
    "german@macars.com.ar",
    "lucas.formia@gmail.com",
)
ADMIN_PRINCIPAL = ADMINES_MAESTROS[0]
TABLAS_ROL = ("perfiles", "profiles", "roles", "usuarios", "usuarios_admin", "administradores")
_tabla_roles: str | None = None
_tabla_roles_revisada = False


def correos_admin() -> set[str]:
    correos = {correo.lower() for correo in ADMINES_MAESTROS}
    crudo = os.getenv("ADMIN_EMAILS", "")
    correos.update(parte.strip().lower() for parte in crudo.split(",") if parte.strip())
    return correos


def es_admin_principal(email: str) -> bool:
    return email.strip().lower() in {correo.lower() for correo in ADMINES_MAESTROS}


def decidir_rol(email: str, app_metadata: dict | None, correos: set[str]) -> tuple[str, int | None] | None:
    """Admin por correo o metadata. Cliente si app_metadata trae cliente_id. Si no, hay que buscar el email."""
    meta = app_metadata or {}
    rol = str(meta.get("role") or meta.get("rol") or "").strip().lower()
    correo = email.strip().lower()
    if correo == ADMIN_PRINCIPAL or correo in correos or rol in ROLES_ADMIN:
        return "admin", None
    cliente_id = meta.get("cliente_id")
    if cliente_id in (None, ""):
        return None
    try:
        return "cliente", int(cliente_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("El cliente vinculado a esta cuenta no es válido.") from exc


def _mensaje_auth(exc: Exception) -> str:
    texto = (getattr(exc, "message", None) or str(exc)).lower()
    if "invalid login" in texto or "invalid credentials" in texto:
        return "Email o contraseña incorrectos."
    if "not confirmed" in texto:
        return "Confirmá el email antes de ingresar."
    if "rate" in texto or "too many" in texto:
        return "Demasiados intentos. Esperá un momento y volvé a intentar."
    return "No se pudo iniciar sesión. Revisá el email y la contraseña."


def _pide_clave_nueva(user) -> bool:
    meta = user.app_metadata or {}
    return bool(meta.get("debe_cambiar_clave"))


def _datos_sesion(user, session, rol: str, cliente_id: int | None) -> dict:
    expira = session.expires_at
    if not expira:
        expira = int(time.time()) + int(session.expires_in or 3600)
    return {
        "email": (user.email or "").strip().lower(),
        "user_id": str(user.id),
        "rol": rol,
        "cliente_id": cliente_id,
        "debe_cambiar_clave": _pide_clave_nueva(user),
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": int(expira),
    }


def _clave_temporal() -> str:
    alfabeto = "abcdefghijkmnpqrstuvwxyz23456789"
    sufijo = "".join(secrets.choice(alfabeto) for _ in range(4))
    return f"Puffco2026!{sufijo}"


def _usuario_por_email(email: str):
    auth = cliente_nuevo()
    for pagina in range(1, 21):
        usuarios = auth.auth.admin.list_users(page=pagina, per_page=200)
        if not usuarios:
            return None
        for usuario in usuarios:
            if (usuario.email or "").strip().lower() == email:
                return usuario
        if len(usuarios) < 200:
            return None
    return None


def _es_cuenta_admin(usuario) -> bool:
    email = (usuario.email or "").strip().lower()
    meta = usuario.app_metadata or {}
    rol = str(meta.get("role") or meta.get("rol") or "").strip().lower()
    return es_admin_principal(email) or rol in ROLES_ADMIN


def generar_acceso_b2b(cliente_id: int, email: str) -> tuple[str, str]:
    """Crea o restablece el acceso del cliente. Devuelve email y clave temporal."""
    limpio, error = normalizar_email(email)
    if error:
        raise ValueError(error)
    if not limpio:
        raise ValueError("Cargá el email de acceso antes de generar la clave.")
    if es_admin_principal(limpio):
        raise ValueError("Ese email es el administrador. Usá el correo del cliente.")
    clave = _clave_temporal()
    meta = {"role": "cliente", "cliente_id": int(cliente_id), "debe_cambiar_clave": True}
    auth = cliente_nuevo()
    usuario = _usuario_por_email(limpio)
    if usuario is not None and _es_cuenta_admin(usuario):
        raise ValueError("Ese email pertenece a un administrador.")
    if usuario is None:
        try:
            auth.auth.admin.create_user(
                {
                    "email": limpio,
                    "password": clave,
                    "email_confirm": True,
                    "app_metadata": meta,
                }
            )
            return limpio, clave
        except AuthApiError as exc:
            texto = (getattr(exc, "message", None) or str(exc)).lower()
            if "already" not in texto and "registered" not in texto and "exists" not in texto:
                raise ValueError("No se pudo crear el acceso.") from exc
            usuario = _usuario_por_email(limpio)
            if usuario is None or _es_cuenta_admin(usuario):
                raise ValueError("No se pudo crear el acceso.") from exc
    meta_actual = dict(usuario.app_metadata or {})
    meta_actual.update(meta)
    try:
        auth.auth.admin.update_user_by_id(
            str(usuario.id),
            {"password": clave, "email_confirm": True, "app_metadata": meta_actual},
        )
    except AuthApiError as exc:
        raise ValueError("No se pudo restablecer la clave.") from exc
    return limpio, clave


def cambiar_clave_cliente(user_id: str, nueva: str) -> None:
    sesion = st.session_state.get(CLAVE_SESION) or {}
    if sesion.get("rol") != "cliente" or sesion.get("user_id") != user_id:
        raise ValueError("No se puede cambiar esta clave.")
    if len(nueva) < 8:
        raise ValueError("La nueva clave tiene que tener al menos 8 caracteres.")
    auth = cliente_nuevo()
    respuesta = auth.auth.admin.get_user_by_id(user_id)
    if respuesta.user is None or _es_cuenta_admin(respuesta.user):
        raise ValueError("No se puede cambiar esta cuenta desde el portal.")
    meta = dict(respuesta.user.app_metadata or {})
    meta["role"] = "cliente"
    meta["debe_cambiar_clave"] = False
    try:
        auth.auth.admin.update_user_by_id(user_id, {"password": nueva, "app_metadata": meta})
    except AuthApiError as exc:
        raise ValueError("No se pudo guardar la contraseña.") from exc
    sesion["debe_cambiar_clave"] = False
    st.session_state[CLAVE_SESION] = sesion


def _tabla_ausente(exc: Exception) -> bool:
    texto = texto_error(exc).lower()
    return any(
        marca in texto
        for marca in ("pgrst205", "could not find the table", "does not exist", "42p01", "schema cache")
    )


def _buscar_tabla_roles(sb) -> str | None:
    global _tabla_roles, _tabla_roles_revisada
    if _tabla_roles_revisada:
        return _tabla_roles
    _tabla_roles_revisada = True
    for tabla in TABLAS_ROL:
        try:
            sb.table(tabla).select("*").limit(1).execute()
        except Exception:
            continue
        _tabla_roles = tabla
        return tabla
    return None


def _sincronizar_tabla_admin(sb, email: str, user_id: str) -> None:
    tabla = _buscar_tabla_roles(sb)
    if not tabla:
        return
    muestra = sb.table(tabla).select("*").limit(1).execute().data or []
    columnas = set(muestra[0].keys()) if muestra else set()
    datos: dict = {}
    if not columnas or "email" in columnas:
        datos["email"] = email
    if "user_id" in columnas:
        datos["user_id"] = user_id
    elif "auth_id" in columnas:
        datos["auth_id"] = user_id
    if "rol" in columnas or not columnas:
        datos["rol"] = "admin"
    elif "role" in columnas:
        datos["role"] = "admin"
    if not datos:
        return
    if "email" in columnas or not columnas:
        existentes = sb.table(tabla).select("*").eq("email", email).limit(1).execute().data or []
        if existentes:
            filtro = "id" if existentes[0].get("id") is not None else "email"
            valor = existentes[0].get("id") if filtro == "id" else email
            sb.table(tabla).update(datos).eq(filtro, valor).execute()
            return
    sb.table(tabla).insert(datos).execute()


def asegurar_admin(sb, user) -> None:
    """Deja a los administradores maestros como admin en Auth y, si existe, en la tabla de roles."""
    email = (user.email or "").strip().lower()
    if not es_admin_principal(email):
        return
    try:
        meta = dict(user.app_metadata or {})
        if str(meta.get("role") or meta.get("rol") or "").strip().lower() not in ROLES_ADMIN:
            meta["role"] = "admin"
            cliente_nuevo().auth.admin.update_user_by_id(str(user.id), {"app_metadata": meta})
    except Exception:
        pass
    try:
        _sincronizar_tabla_admin(sb, email, str(user.id))
    except Exception:
        pass


def _resolver(sb, user) -> tuple[str, int | None]:
    email = (user.email or "").strip().lower()
    decision = decidir_rol(email, user.app_metadata, correos_admin())
    if decision and decision[0] == "admin":
        asegurar_admin(sb, user)
        return decision
    if decision and decision[0] == "cliente":
        cliente = leer_cliente_por_id(sb, int(decision[1]))
        if not cliente or not esta_activo(cliente):
            raise ValueError("El cliente vinculado a esta cuenta no existe o está inactivo.")
        return "cliente", int(cliente["id"])
    cliente = leer_cliente_por_email(sb, email)
    if cliente:
        return "cliente", int(cliente["id"])
    raise ValueError("Esta cuenta no está habilitada. Pedile al administrador que la vincule.")


def _revocar(sesion: dict | None) -> None:
    if not sesion:
        return
    try:
        cliente = cliente_nuevo()
        cliente.auth.set_session(sesion["access_token"], sesion["refresh_token"])
        cliente.auth.sign_out({"scope": "global"})
    except Exception:
        return


def iniciar_sesion(sb, email: str, clave: str) -> None:
    email = email.strip().lower()
    if "@" not in email or not clave:
        raise ValueError("Completá el email y la contraseña.")
    auth = cliente_nuevo()
    try:
        respuesta = auth.auth.sign_in_with_password({"email": email, "password": clave})
    except AuthInvalidCredentialsError as exc:
        raise ValueError("Email o contraseña incorrectos.") from exc
    except AuthApiError as exc:
        raise ValueError(_mensaje_auth(exc)) from exc
    if respuesta.user is None or respuesta.session is None:
        raise ValueError("No se pudo iniciar sesión.")
    try:
        rol, cliente_id = _resolver(sb, respuesta.user)
    except Exception:
        try:
            auth.auth.sign_out({"scope": "global"})
        except Exception:
            pass
        raise
    st.session_state[CLAVE_SESION] = _datos_sesion(respuesta.user, respuesta.session, rol, cliente_id)


def _refrescar(sb, sesion: dict) -> dict:
    auth = cliente_nuevo()
    respuesta = auth.auth.refresh_session(sesion["refresh_token"])
    if respuesta.user is None or respuesta.session is None:
        raise RuntimeError("sesión vencida")
    rol, cliente_id = _resolver(sb, respuesta.user)
    return _datos_sesion(respuesta.user, respuesta.session, rol, cliente_id)


def _olvidar() -> None:
    st.session_state.pop(CLAVE_SESION, None)
    st.session_state.pop("impersonated_client_id", None)
    st.session_state["carrito"] = {}


def cerrar_sesion() -> None:
    sesion = st.session_state.get(CLAVE_SESION)
    _olvidar()
    _revocar(sesion)


def usuario_actual(sb) -> dict | None:
    sesion = st.session_state.get(CLAVE_SESION)
    if not sesion:
        return None
    if int(sesion.get("expires_at") or 0) <= int(time.time()) + 60:
        try:
            sesion = _refrescar(sb, sesion)
        except ValueError as exc:
            _olvidar()
            st.session_state["aviso_auth"] = str(exc)
            return None
        except Exception:
            _olvidar()
            st.session_state["aviso_auth"] = "La sesión venció. Volvé a ingresar."
            return None
        st.session_state[CLAVE_SESION] = sesion
    if sesion.get("rol") == "admin":
        return {"rol": "admin", "email": sesion["email"], "cliente": None, "user_id": sesion.get("user_id")}
    cliente_id = sesion.get("cliente_id")
    if sesion.get("rol") != "cliente" or not cliente_id:
        _olvidar()
        st.session_state["aviso_auth"] = "Esta cuenta no está habilitada."
        return None
    try:
        cliente = leer_cliente_por_id(sb, int(cliente_id))
    except Exception as exc:
        st.error(f"No se pudo verificar la sesión. {texto_error(exc)}")
        st.stop()
    if not cliente or not esta_activo(cliente):
        _olvidar()
        st.session_state["aviso_auth"] = "El cliente de esta cuenta no está activo."
        return None
    return {
        "rol": "cliente",
        "email": sesion["email"],
        "cliente": cliente,
        "user_id": sesion.get("user_id"),
        "debe_cambiar_clave": bool(sesion.get("debe_cambiar_clave")),
    }
