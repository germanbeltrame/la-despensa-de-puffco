-- Catálogo público para la clave anónima.
-- Ejecutar en el SQL Editor de Supabase.
-- Permite leer solo foto, nombre, marca, categoría y activo.
-- Precios, stock y costos quedan fuera de ese permiso.

revoke select on table public.productos from anon;

grant select (nombre, marca, categoria, imagen_url, activo)
on table public.productos
to anon;

alter table public.productos enable row level security;

drop policy if exists catalogo_publico_lectura on public.productos;

create policy catalogo_publico_lectura
on public.productos
for select
to anon
using (activo is not false);
