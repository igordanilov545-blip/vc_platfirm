from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('blog', '0047_legacy_base_import')]
    operations = [
        migrations.AddField(model_name='user', name='appearance', field=models.CharField(
            choices=[('nexus', 'Nexus'), ('minecraft', 'Minecraft')], default='nexus', max_length=32)),
        migrations.AddField(model_name='user', name='color_theme', field=models.CharField(
            choices=[('system', 'Как на устройстве'), ('light', 'Светлая'), ('dark', 'Тёмная')],
            default='system', max_length=10)),
    ]
