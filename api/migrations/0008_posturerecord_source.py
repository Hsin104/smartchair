from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0007_chairsession_baseline'),
    ]

    operations = [
        migrations.AddField(
            model_name='posturerecord',
            name='source',
            field=models.CharField(
                choices=[('real', '真實採集'), ('fake', '假資料'), ('auto', '自動預測')],
                default='auto',
                max_length=10,
                verbose_name='資料來源',
            ),
        ),
    ]
