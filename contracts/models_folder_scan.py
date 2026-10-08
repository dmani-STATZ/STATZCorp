"""SharePoint contract folder scan snapshot models."""

from django.conf import settings
from django.db import models


class FolderScanRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        ABANDONED = 'abandoned', 'Abandoned'

    root_path = models.CharField(max_length=500, blank=True, default='', db_index=True)
    company_ids = models.CharField(max_length=200, blank=True, default='')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    started_by = models.CharField(max_length=150, blank=True, default='')
    apply_requested = models.BooleanField(default=False)
    current_path = models.CharField(max_length=1000, blank=True, default='')

    folders_saved = models.PositiveIntegerField(default=0)
    graph_calls = models.PositiveIntegerField(default=0)
    graph_retries = models.PositiveIntegerField(default=0)
    contract_folders = models.PositiveIntegerField(default=0)
    delivery_order_folders = models.PositiveIntegerField(default=0)
    other_folders = models.PositiveIntegerField(default=0)
    matched_expected = models.PositiveIntegerField(default=0)
    matched_elsewhere = models.PositiveIntegerField(default=0)
    matched_no_db_path = models.PositiveIntegerField(default=0)
    matched_idiq = models.PositiveIntegerField(default=0)
    no_contract_in_db = models.PositiveIntegerField(default=0)
    duplicate_folders = models.PositiveIntegerField(default=0)
    contracts_without_folder = models.PositiveIntegerField(default=0)
    do_parent_mismatch = models.PositiveIntegerField(default=0)
    drive_ids_written = models.PositiveIntegerField(default=0)
    idiq_drive_ids_written = models.PositiveIntegerField(default=0)
    paths_fixed = models.PositiveIntegerField(default=0)

    class ScanMode(models.TextChoices):
        FULL = 'full', 'Full'
        INCREMENTAL = 'incremental', 'Incremental'

    scan_mode = models.CharField(
        max_length=20,
        choices=ScanMode.choices,
        default=ScanMode.FULL,
        blank=True,
    )
    delta_link = models.TextField(blank=True, default='')
    delta_pages = models.PositiveIntegerField(default=0)
    items_seen = models.PositiveIntegerField(default=0)
    files_skipped = models.PositiveIntegerField(default=0)
    deleted_seen = models.PositiveIntegerField(default=0)
    folders_in_scope = models.PositiveIntegerField(default=0)
    folders_added = models.PositiveIntegerField(default=0)
    folders_changed = models.PositiveIntegerField(default=0)
    folders_removed = models.PositiveIntegerField(default=0)
    graph_seconds = models.FloatField(default=0.0)
    db_seconds = models.FloatField(default=0.0)

    error_message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']

    def __str__(self) -> str:
        return f'FolderScanRun({self.root_path!r}, {self.status})'


class ScannedFolder(models.Model):
    class FolderKind(models.TextChoices):
        CONTRACT = 'contract', 'Contract'
        DELIVERY_ORDER = 'delivery_order', 'Delivery order'
        OTHER = 'other', 'Other'

    class MatchStatus(models.TextChoices):
        MATCHED_EXPECTED = 'matched_expected', 'Matched expected'
        MATCHED_ELSEWHERE = 'matched_elsewhere', 'Matched elsewhere'
        MATCHED_NO_DB_PATH = 'matched_no_db_path', 'Matched no DB path'
        MATCHED_IDIQ = 'matched_idiq', 'Matched IDIQ'
        NO_CONTRACT_IN_DB = 'no_contract_in_db', 'No contract in DB'
        DUPLICATE = 'duplicate', 'Duplicate'
        NOT_CONTRACT_FOLDER = 'not_contract_folder', 'Not contract folder'

    class DoParentStatus(models.TextChoices):
        OK = 'ok', 'OK'
        MISMATCH = 'mismatch', 'Mismatch'
        NO_IDIQ_IN_DB = 'no_idiq_in_db', 'No IDIQ in DB'
        NOT_NESTED = 'not_nested', 'Not nested'
        NOT_APPLICABLE = 'not_applicable', 'Not applicable'

    run = models.ForeignKey(
        FolderScanRun,
        on_delete=models.CASCADE,
        related_name='folders',
    )
    drive_item_id = models.CharField(max_length=128, blank=True, default='')
    parent_drive_item_id = models.CharField(max_length=128, blank=True, default='')
    name = models.CharField(max_length=400, blank=True, default='')
    path = models.CharField(max_length=1000, blank=True, default='')
    depth = models.PositiveSmallIntegerField(default=0)
    web_url = models.CharField(max_length=1000, blank=True, default='')
    folder_kind = models.CharField(
        max_length=20,
        choices=FolderKind.choices,
        default=FolderKind.OTHER,
    )
    parsed_contract_number = models.CharField(max_length=100, blank=True, default='')
    normalized_contract_number = models.CharField(max_length=100, blank=True, default='')
    contract = models.ForeignKey(
        'Contract',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='scanned_folders',
    )
    idiq_contract = models.ForeignKey(
        'IdiqContract',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='scanned_folders',
    )
    match_status = models.CharField(
        max_length=30,
        choices=MatchStatus.choices,
        default=MatchStatus.NOT_CONTRACT_FOLDER,
    )
    files_url_at_scan = models.CharField(max_length=1000, blank=True, default='')
    parent_contract_number = models.CharField(max_length=100, blank=True, default='')
    do_parent_status = models.CharField(
        max_length=20,
        choices=DoParentStatus.choices,
        default=DoParentStatus.NOT_APPLICABLE,
    )
    in_scope = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['run', 'normalized_contract_number']),
            models.Index(fields=['run', 'drive_item_id']),
        ]

    def __str__(self) -> str:
        return self.path or self.name


class FolderScanLog(models.Model):
    class Level(models.TextChoices):
        INFO = 'INFO', 'Info'
        WARN = 'WARN', 'Warn'
        ERROR = 'ERROR', 'Error'

    run = models.ForeignKey(
        FolderScanRun,
        on_delete=models.CASCADE,
        related_name='logs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    level = models.CharField(
        max_length=10,
        choices=Level.choices,
        default=Level.INFO,
    )
    message = models.CharField(max_length=2000, blank=True, default='')

    class Meta:
        ordering = ['id']

    def __str__(self) -> str:
        return f'{self.level}: {self.message[:80]}'


class FolderReviewIgnore(models.Model):
    class Queue(models.TextChoices):
        PAIRS = 'pairs', 'Pair up'
        MISNAMED = 'misnamed', 'Misnamed'
        DUPLICATES = 'duplicates', 'Duplicates'
        ORPHANS = 'orphans', 'Orphan folders'
        FOLDERLESS = 'folderless', 'Contracts without folder'
        MOVER = 'mover', 'Waiting to move'
        DO_MISMATCH = 'do_mismatch', 'DO under wrong IDIQ'
        QUICK_FIX = 'quick_fix', 'Quick fixes'
        NAME_MISMATCH = 'name_mismatch', "Name doesn't match"
        MOVE_CLOSED = 'move_closed', 'Move to Closed'
        READY_TO_MERGE = 'ready_to_merge', 'Ready to merge'

    queue = models.CharField(
        max_length=30,
        choices=Queue.choices,
        blank=True,
        default='',
    )
    drive_item_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    contract = models.ForeignKey(
        'Contract',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='+',
    )
    note = models.CharField(max_length=500, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f'FolderReviewIgnore({self.queue}, {self.drive_item_id or self.contract_id})'


class FolderRepairLog(models.Model):
    class Action(models.TextChoices):
        LINK_PAIR = 'link_pair', 'Link pair'
        LINK_MISNAMED = 'link_misnamed', 'Link misnamed'
        MANUAL_MATCH = 'manual_match', 'Manual match'
        PICK_DUPLICATE = 'pick_duplicate', 'Pick duplicate'
        QUICK_FIX = 'quick_fix', 'Quick fix'
        IGNORE = 'ignore', 'Ignore'
        UNIGNORE = 'unignore', 'Unignore'
        RENAME = 'rename', 'Rename'
        MOVE_CLOSED = 'move_closed', 'Move closed'
        MERGE_MOVE = 'merge_move', 'Merge move child'
        MERGE_COMPLETE = 'merge_complete', 'Merge complete loser'
        MOVE_DO = 'move_do', 'Move DO under IDIQ'

    action = models.CharField(
        max_length=30,
        choices=Action.choices,
        blank=True,
        default='',
    )
    contract = models.ForeignKey(
        'Contract',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    idiq_contract = models.ForeignKey(
        'IdiqContract',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    drive_item_id = models.CharField(max_length=128, blank=True, default='')
    old_files_url = models.CharField(max_length=1000, blank=True, default='')
    new_files_url = models.CharField(max_length=1000, blank=True, default='')
    old_drive_item_id = models.CharField(max_length=128, blank=True, default='')
    new_drive_item_id = models.CharField(max_length=128, blank=True, default='')
    detail = models.CharField(max_length=1000, blank=True, default='')
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self) -> str:
        return f'FolderRepairLog({self.action}, {self.pk})'
