from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(name="LoginAttemptBucket", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("key", models.CharField(max_length=64, unique=True)),
        ("started_at", models.DateTimeField()),
        ("attempts", models.PositiveIntegerField(default=0)),
    ])]
