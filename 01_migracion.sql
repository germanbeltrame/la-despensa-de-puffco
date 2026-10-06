-- Migración: ficha de cuenta y Row Level Security.
-- Ejecutar en el SQL Editor de Supabase.

alter table public.clientes
  add column if not exists tiene_ficha boolean default false;

-- Clientes que antes estaban fijos en CUENTAS_CON_FICHA.
update public.clientes
set tiene_ficha = true
where lower(regexp_replace(btrim(nombre), '\s+', ' ', 'g')) in (
  'agus honney',
  'alan',
  'ale ong cordoba',
  'alfredo indajaus',
  'alto vuelo',
  'charly distri',
  'coco salta',
  'conex distribuidora',
  'facu lp',
  'facu pisando',
  'guille naesa',
  'high up omg',
  'kanario',
  'lean tegridad',
  'leloir ong',
  'lt grow',
  'marshal lean',
  'nahu la comarca',
  'old farmers',
  'pedro',
  'the pot club',
  'tin uy',
  'tuki grow',
  'vaporever'
);

-- RLS en todas las tablas de public.
-- Cualquier usuario autenticado puede leer y escribir.
-- service_role sigue sin pasar por estas políticas.
-- Se vuelve a dejar la lectura anónima del catálogo público de productos.

do $$
declare
  tabla text;
  nombre_politica text;
begin
  for tabla in
    select tablename
    from pg_tables
    where schemaname = 'public'
  loop
    execute format('alter table public.%I enable row level security', tabla);
    nombre_politica := tabla || '_authenticated_all';
    execute format('drop policy if exists %I on public.%I', nombre_politica, tabla);
    execute format(
      'create policy %I on public.%I for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null)',
      nombre_politica,
      tabla
    );
  end loop;
end $$;

drop policy if exists catalogo_publico_lectura on public.productos;

create policy catalogo_publico_lectura
on public.productos
for select
to anon
using (activo is not false);
