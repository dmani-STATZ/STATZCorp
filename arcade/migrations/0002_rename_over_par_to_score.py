# Generated manually for RenameField data preservation (Phase B).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("arcade", "0001_initial"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="arcadeattempt",
            name="idx_arcade_leaderboard",
        ),
        migrations.RenameField(
            model_name="arcadeattempt",
            old_name="over_par",
            new_name="score",
        ),
        migrations.AlterField(
            model_name="arcadeattempt",
            name="score",
            field=models.IntegerField(
                blank=True,
                help_text=(
                    "Lower is better. Comparable only within the same game_key "
                    "(never across games). Set on completion."
                ),
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="arcadeattempt",
            name="par",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="arcadeattempt",
            index=models.Index(
                fields=["game_key", "puzzle_date", "score", "active_ms"],
                name="idx_arcade_leaderboard",
            ),
        ),
    ]
