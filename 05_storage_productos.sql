-- Bucket público de fotos de productos. Ejecutar en el SQL Editor de Supabase.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'productos',
  'productos',
  true,
  5242880,
  array['image/png', 'image/jpeg', 'image/webp']
)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists productos_public_select on storage.objects;
create policy productos_public_select
on storage.objects
for select
to public
using (bucket_id = 'productos');

drop policy if exists productos_authenticated_insert on storage.objects;
create policy productos_authenticated_insert
on storage.objects
for insert
to authenticated
with check (bucket_id = 'productos');

drop policy if exists productos_authenticated_update on storage.objects;
create policy productos_authenticated_update
on storage.objects
for update
to authenticated
using (bucket_id = 'productos')
with check (bucket_id = 'productos');

drop policy if exists productos_authenticated_delete on storage.objects;
create policy productos_authenticated_delete
on storage.objects
for delete
to authenticated
using (bucket_id = 'productos');
