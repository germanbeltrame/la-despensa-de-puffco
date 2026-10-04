# 📦 ERP PUFFCO APP - Documentación de Estado y Roadmap

## ✅ FASE 1 COMPLETADA (Funcionalidades y Calibración):

1. **Gestión de Inventario y Validación Matemática de Costos:**
   - Implementada regla matemática de validación de costos: `Si M > H -> usar H` para resolver incoherencias de FOBs inflados.
   - Soporte para **Costo por Fórmula** (`FOB + Peso × Tarifa KG + Fees`) y **Costo Manual**.
   - Identificación visual de **`⚠️ Incompleto`** y filtro aislado para 228 artículos a revisar.
   - Implementación de **Bajas Lógicas** (`soft delete`) e Importador/Actualizador masivo por Excel/CSV.

2. **Punto de Venta Ágil (`views/nuevas_ventas.py`):**
   - Layout dinámico en 2 columnas con resumen financiero en vivo (Venta, Costo, Ganancia Real y Margen %).
   - **Bloqueo de Cliente Fijo** para evitar cambios de precios u operaciones cruzadas durante la orden.
   - Búsqueda predictiva rápida entre los 356 productos del catálogo.

3. **Cuentas Corrientes e Integridad Financiera (`views/cuentas_corrientes.py` & `views/registrar_pago.py`):**
   - Conciliación de deuda global en **US$ 59,350.59**.
   - Cobranzas con modalidad **A Cuenta** o **Imputación a Pedido/Factura Específica**.
   - Análisis de antigüedad de deuda en días de mora e indicadores por colores.
   - Módulo de exportación de estados de cuenta a **Excel** y **PDF**.

4. **Reportes y Analítica Directiva (`views/reportes.py`):**
   - Separación de rango personalizado en dos selectores independientes (`Fecha desde` / `Fecha hasta`).
   - Reemplazo del filtro de Categoría por **Marca** para análisis de facturación y margen por proveedor.
   - Sugerido de reposición de stock proyectado a 30 días.

---

## 🚀 FASE 2 ROADMAP (Autenticación, Portal B2B y Gestión de Pedidos):

### 1. Sistema de Autenticación en Supabase (Auth):
- **Rol Administrador:**
  - Login con email de Administrador configurado en Supabase Auth.
  - Acceso total al Mini ERP (Inventario, Clientes, Ventas, Pagos, Cuentas Corrientes y Reportes).
- **Rol Cliente (Portal B2B):**
  - Login individual por cliente.
  - Estado **Sin Loguear (Público):** Permite navegar el catálogo de productos (fotos y descripciones) **SIN mostrar precios ni stock**.
  - Estado **Logueado (Cliente):** Habilita la visibilidad de sus precios (Estándar o Distribuidor), consulta de su saldo en Cuenta Corriente, historial de compras y panel de **Pre-Venta / Solicitud de Pedido**.

### 2. Módulo de Recepción de Pedidos (Pre-Venta):
- Los pedidos creados por los clientes quedan en estado **`Pendiente de Aprobación`**.
- El Administrador cuenta con un panel de recepción donde revisa el estado crediticio del cliente en Cuenta Corriente antes de aprobar y convertir la orden en una **Venta Real**.
