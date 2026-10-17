from django.db import migrations


TABLES = ('hotspot_router', 'hotspot_branding', 'hotspot_accessgrant', 'hotspot_auditlog')


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in TABLES:
        schema_editor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f"""
            CREATE POLICY novainfo_tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('novainfo.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('novainfo.tenant_id', true), '')::uuid)
        """)


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in TABLES:
        schema_editor.execute(f'DROP POLICY IF EXISTS novainfo_tenant_isolation ON {table}')
        schema_editor.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [('hotspot', '0001_initial')]
    operations = [migrations.RunPython(enable_rls, disable_rls)]
