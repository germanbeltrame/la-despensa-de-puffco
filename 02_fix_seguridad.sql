-- Escritura para usuarios autenticados.
-- Ejecutar en el SQL Editor de Supabase después de 01_migracion.sql.
-- Sin política de SELECT, un UPDATE puede "salir bien" y no devolver la fila.

do $$
declare
  tabla text;
  tablas text[] := array[
    'productos',
    'clientes',
    'configuracion',
    'pedidos',
    'pagos',
    'detalle_pedidos',
    'tipos_flete'
  ];
begin
  foreach tabla in array tablas
  loop
    if to_regclass('public.' || tabla) is null then
      continue;
    end if;

    execute format(
      'grant select, insert, update, delete on table public.%I to authenticated',
      tabla
    );
    execute format('alter table public.%I enable row level security', tabla);

    execute format('drop policy if exists %I on public.%I', tabla || '_authenticated_select', tabla);
    execute format(
      'create policy %I on public.%I for select to authenticated using (true)',
      tabla || '_authenticated_select',
      tabla
    );

    execute format('drop policy if exists %I on public.%I', tabla || '_authenticated_insert', tabla);
    execute format(
      'create policy %I on public.%I for insert to authenticated with check (true)',
      tabla || '_authenticated_insert',
      tabla
    );

    execute format('drop policy if exists %I on public.%I', tabla || '_authenticated_update', tabla);
    execute format(
      'create policy %I on public.%I for update to authenticated using (true) with check (true)',
      tabla || '_authenticated_update',
      tabla
    );

    execute format('drop policy if exists %I on public.%I', tabla || '_authenticated_delete', tabla);
    execute format(
      'create policy %I on public.%I for delete to authenticated using (true)',
      tabla || '_authenticated_delete',
      tabla
    );
  end loop;
end $$;

grant usage, select on all sequences in schema public to authenticated;
