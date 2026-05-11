import logging
from datetime import date, datetime
from pathlib import Path

import frontmatter
from django.conf import settings
from django.core.management.base import BaseCommand

from users.models import ReleaseNote
from users.release_notes.constants import AREAS, CHANGE_TYPES

logger = logging.getLogger(__name__)


def _classify_tags(tag_list):
    if not isinstance(tag_list, list):
        return None, None, "tags must be a YAML list"
    unknown = [t for t in tag_list if t not in CHANGE_TYPES and t not in AREAS]
    if unknown:
        return None, None, f"unknown tags: {unknown!r}"
    types_found = [t for t in tag_list if t in CHANGE_TYPES]
    areas_found = [t for t in tag_list if t in AREAS]
    if len(tag_list) != 2 or len(types_found) != 1 or len(areas_found) != 1:
        return (
            None,
            None,
            "tags must contain exactly one CHANGE_TYPE and one AREA (two entries total)",
        )
    return types_found[0], areas_found[0], None


def _parse_bool(val, field_name):
    if isinstance(val, bool):
        return val, None
    if val is None:
        return None, f"missing {field_name}"
    return None, f"{field_name} must be a boolean"


def _parse_publish_date(val):
    if val is None:
        return None, "missing publish_date"
    if isinstance(val, datetime):
        return val.date(), None
    if isinstance(val, date):
        return val, None
    if isinstance(val, str):
        try:
            y, m, d = val.strip()[:10].split("-")
            return date(int(y), int(m), int(d)), None
        except (ValueError, TypeError):
            pass
    return None, "publish_date must be an ISO date (YYYY-MM-DD)"


class Command(BaseCommand):
    help = "Import release notes from release_notes/*.md into the database (idempotent, fail-soft)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report actions without writing to the database.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Extra logging to stderr.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        verbose = options["verbose"]
        if verbose:
            logging.getLogger("users.management.commands.import_release_notes").setLevel(
                logging.DEBUG
            )

        notes_dir = Path(settings.BASE_DIR) / "release_notes"
        if not notes_dir.is_dir():
            self.stdout.write(self.style.WARNING(f"Release notes directory missing: {notes_dir}"))
            self.stdout.write("Imported: 0 new, 0 updated, 0 skipped, 0 errors")
            return

        new_c = updated_c = skipped_c = errors_c = 0
        seen_files = set()

        for path in sorted(notes_dir.glob("*.md")):
            if path.name.upper() == "README.MD":
                continue
            stem = path.stem
            seen_files.add(stem)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as e:
                errors_c += 1
                logger.warning("Could not read release note file %s: %s", path, e)
                continue

            try:
                post = frontmatter.loads(text)
            except Exception as e:
                errors_c += 1
                logger.warning("Frontmatter parse failed for %s: %s", path, e)
                continue

            meta = post.metadata or {}
            body = (post.content or "").strip()

            note_id = meta.get("id")
            if not note_id or str(note_id) != stem:
                errors_c += 1
                logger.warning(
                    "Invalid id in %s: expected %r to match filename stem",
                    path,
                    stem,
                )
                continue

            title = (meta.get("title") or "").strip()
            if not title:
                errors_c += 1
                logger.warning("Missing or empty title in %s", path)
                continue

            pub, err = _parse_publish_date(meta.get("publish_date"))
            if err:
                errors_c += 1
                logger.warning("%s in %s", err, path)
                continue

            published, err = _parse_bool(meta.get("published"), "published")
            if err:
                errors_c += 1
                logger.warning("%s in %s", err, path)
                continue

            if not published:
                skipped_c += 1
                logger.debug("Skipping unpublished file %s", path)
                if dry_run:
                    self.stdout.write(f"[DRY RUN] skip unpublished: {path.name}")
                continue

            change_type, area, terr = _classify_tags(meta.get("tags"))
            if terr:
                errors_c += 1
                logger.warning("%s in %s", terr, path)
                continue

            critical_raw = meta.get("critical", False)
            critical, cerr = _parse_bool(critical_raw, "critical")
            if cerr:
                errors_c += 1
                logger.warning("%s in %s", cerr, path)
                continue

            if not body:
                errors_c += 1
                logger.warning("Empty body in %s", path)
                continue

            try:
                existing = ReleaseNote.objects.filter(note_id=note_id).first()
            except Exception as e:
                logger.warning("DB lookup failed for %s: %s", note_id, e)
                errors_c += 1
                continue

            if existing is None:
                if dry_run:
                    self.stdout.write(f"[DRY RUN] would insert: {note_id}")
                if not dry_run:
                    try:
                        ReleaseNote.objects.create(
                            note_id=note_id,
                            title=title,
                            body_markdown=body,
                            publish_date=pub,
                            change_type=change_type,
                            area=area,
                            critical=critical,
                        )
                    except Exception as e:
                        errors_c += 1
                        logger.warning("Insert failed for %s: %s", path, e)
                        continue
                new_c += 1
                continue

            differs = (
                existing.title != title
                or existing.body_markdown != body
                or existing.publish_date != pub
                or existing.change_type != change_type
                or existing.area != area
                or existing.critical != critical
            )
            if differs:
                if dry_run:
                    self.stdout.write(f"[DRY RUN] would update: {note_id}")
                if not dry_run:
                    try:
                        existing.title = title
                        existing.body_markdown = body
                        existing.publish_date = pub
                        existing.change_type = change_type
                        existing.area = area
                        existing.critical = critical
                        existing.save()
                    except Exception as e:
                        errors_c += 1
                        logger.warning("Update failed for %s: %s", path, e)
                        continue
                updated_c += 1
            else:
                skipped_c += 1
                if dry_run:
                    self.stdout.write(f"[DRY RUN] skip unchanged: {note_id}")

        # DB rows with no file on disk
        try:
            for row in ReleaseNote.objects.all().only("note_id"):
                if row.note_id not in seen_files:
                    logger.warning(
                        "ReleaseNote %r exists in DB but has no matching markdown file (manual cleanup only)",
                        row.note_id,
                    )
        except Exception as e:
            logger.warning("Orphan DB scan failed: %s", e)

        self.stdout.write(
            f"Imported: {new_c} new, {updated_c} updated, {skipped_c} skipped, {errors_c} errors"
        )
