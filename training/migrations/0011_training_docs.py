from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("training", "0010_course_review_doc_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="course",
            name="document_name",
        ),
        migrations.RemoveField(
            model_name="course",
            name="document_date",
        ),
        migrations.RemoveField(
            model_name="coursereviewclick",
            name="reviewed_document_name",
        ),
        migrations.RemoveField(
            model_name="coursereviewclick",
            name="reviewed_document_date",
        ),
        migrations.CreateModel(
            name="TrainingDoc",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("file_blob", models.BinaryField()),
                ("file_name", models.CharField(max_length=255)),
                ("file_date", models.DateField(blank=True, null=True)),
                ("file_hash", models.CharField(blank=True, max_length=64, null=True)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "course",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="docs",
                        to="training.course",
                    ),
                ),
            ],
            options={
                "ordering": ["-uploaded_at", "-id"],
            },
        ),
        migrations.AddField(
            model_name="coursereviewclick",
            name="reviewed_doc",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                to="training.trainingdoc",
            ),
        ),
    ]
