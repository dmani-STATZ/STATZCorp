from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
from contracts.models import (
    AuditModel, Buyer, Company, Nsn, Supplier, ContractType, Contract,
    Clin, IdiqContract, SalesClass, ClinType, SpecialPaymentTerms
)

class QueueContract(AuditModel):
    """Model for storing queued contracts before they become live contracts"""
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='queue_contracts', null=False, blank=True)
    contract_number = models.CharField(max_length=25, null=True, blank=True)
    idiq_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="IDIQ Contract Number",
        help_text=(
            "Populated automatically when this contract originated from a DIBBS "
            "delivery order. Stores the IDIQ parent contract number as a hint for "
            "the analyst to match the IDIQ contract in the processing form."
        ),
    )
    buyer = models.CharField(max_length=255, null=True, blank=True)  # String value to be matched later
    contractor_name = models.CharField(max_length=255, null=True, blank=True)
    contractor_cage = models.CharField(max_length=20, null=True, blank=True)
    award_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    contract_value = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    contract_type = models.CharField(max_length=50, null=True, blank=True)  # Unilateral, Bilateral, IDIQ
    solicitation_type = models.CharField(max_length=50, null=True, blank=True, default='SDVOSB')
    pr_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="PR Number")
    
    # Status tracking
    is_being_processed = models.BooleanField(default=False)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processing_contracts')
    processing_started = models.DateTimeField(null=True, blank=True)

    pdf_parse_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('success', 'Success'),
            ('partial', 'Parsed with Errors'),
        ],
        default='pending'
    )

    pdf_parsed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    pdf_parse_notes = models.TextField(
        null=True,
        blank=True
    )

    sharepoint_folder_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('created', 'Created'),
            ('exists', 'Already Exists'),
            ('error', 'Error'),
        ],
        default='pending',
    )
    sharepoint_folder_url = models.CharField(max_length=500, null=True, blank=True)
    award_pdf_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Not Uploaded'),
            ('uploaded', 'Uploaded'),
            ('error', 'Upload Error'),
        ],
        default='pending',
    )
    sharepoint_notes = models.TextField(null=True, blank=True)

    description = models.TextField(
        null=True,
        blank=True,
        help_text=(
            "Shadow-schema metadata for special contract types. "
            "IDIQ format: IDIQ_META|TERM:<months>|MAX:<value>|MIN:<value>"
        ),
    )

    # Matched references (after processing)
    matched_buyer = models.ForeignKey(Buyer, on_delete=models.SET_NULL, null=True, blank=True)
    matched_contract_type = models.ForeignKey(ContractType, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['contract_number'], name='queue_contract_number_idx'),
            models.Index(fields=['is_being_processed'], name='queue_processing_idx'),
            models.Index(fields=['created_on'], name='queue_created_idx'),
            models.Index(fields=['matched_buyer'], name='queue_buyer_idx'),
            models.Index(fields=['matched_contract_type'], name='queue_contract_type_idx'),
        ]

    def __str__(self):
        return f"Queued Contract {self.contract_number}"

    def save(self, *args, **kwargs):
        if not self.company_id:
            self.company = Company.get_default_company()
        super().save(*args, **kwargs)

class QueueClin(AuditModel):
    """Model for storing queued CLINs before they become live CLINs"""
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='queue_clins', null=False, blank=True)
    contract_queue = models.ForeignKey(QueueContract, on_delete=models.CASCADE, related_name='clins')
    item_number = models.CharField(max_length=20, null=True, blank=True)
    item_type = models.CharField(max_length=20, null=True, blank=True)  # FAT, PVT, Production
    nsn = models.CharField(max_length=20, null=True, blank=True)  # String value to be matched later
    nsn_description = models.TextField(null=True, blank=True)
    ia = models.CharField(max_length=5, null=True, blank=True, choices=[('O', 'Origin'), ('D', 'Destination')])
    fob = models.CharField(max_length=5, null=True, blank=True, choices=[('O', 'Origin'), ('D', 'Destination')])
    due_date = models.DateField(null=True, blank=True)
    order_qty = models.FloatField(null=True, blank=True)
    item_value = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    uom = models.CharField(max_length=10, null=True, blank=True)
    
    # Optional supplier information
    supplier = models.CharField(max_length=255, null=True, blank=True)  # String value to be matched later
    supplier_due_date = models.DateField(null=True, blank=True)
    supplier_unit_price = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    supplier_price = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    supplier_payment_terms = models.CharField(max_length=50, null=True, blank=True)
    
    # Matched references (after processing)
    matched_nsn = models.ForeignKey(Nsn, on_delete=models.SET_NULL, null=True, blank=True)
    matched_supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['contract_queue'], name='queue_clin_contract_idx'),
            models.Index(fields=['item_number'], name='queue_clin_item_idx'),
            models.Index(fields=['nsn'], name='queue_clin_nsn_idx'),
            models.Index(fields=['supplier'], name='queue_clin_supplier_idx'),
            models.Index(fields=['due_date'], name='queue_clin_due_idx'),
            models.Index(fields=['matched_nsn'], name='queue_clin_matched_nsn_idx'),
            models.Index(fields=['matched_supplier'], name='queue_clin_supplier_match_idx'),
        ]

    def __str__(self):
        return f"Queued CLIN {self.item_number} for Contract {self.contract_queue.contract_number}"

    def save(self, *args, **kwargs):
        if not self.company_id:
            if self.contract_queue and self.contract_queue.company_id:
                self.company_id = self.contract_queue.company_id
            else:
                self.company = Company.get_default_company()
        super().save(*args, **kwargs)

class SequenceNumber(models.Model):
    """Model to store and manage auto-incrementing sequence numbers"""
    po_number = models.BigIntegerField(default=10000)  # Starting value
    tab_number = models.BigIntegerField(default=10000)  # Starting value

    @classmethod
    def get_po_number(cls):
        """Get the current PO number without advancing it"""
        sequence = cls.objects.first()
        if not sequence:
            sequence = cls.objects.create()
        return sequence.po_number

    @classmethod
    def get_tab_number(cls):
        """Get the current Tab number without advancing it"""
        sequence = cls.objects.first()
        if not sequence:
            sequence = cls.objects.create()
        return sequence.tab_number

    @classmethod
    def advance_po_number(cls):
        """Get the current PO number and advance it"""
        sequence = cls.objects.first()
        if not sequence:
            sequence = cls.objects.create()
        current = sequence.po_number
        sequence.po_number += 1
        sequence.save()
        return current

    @classmethod
    def advance_tab_number(cls):
        """Get the current Tab number and advance it"""
        sequence = cls.objects.first()
        if not sequence:
            sequence = cls.objects.create()
        current = sequence.tab_number
        sequence.tab_number += 1
        sequence.save()
        return current

class ProcessContract(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('ready_for_review', 'Ready for Review'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='processing_contracts', null=False, blank=True)
    idiq_contract = models.ForeignKey(IdiqContract, on_delete=models.CASCADE, null=True, blank=True)
    contract_number = models.CharField(max_length=25, null=True, blank=True, unique=True)
    solicitation_type = models.CharField(max_length=50, null=True, blank=True, default='SDVOSB')
    pr_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="PR Number")
    po_number = models.CharField(max_length=10, null=True, blank=True)
    tab_num = models.CharField(max_length=10, null=True, blank=True)
    buyer = models.ForeignKey(Buyer, on_delete=models.CASCADE, null=True, blank=True)
    buyer_text = models.CharField(max_length=255, null=True, blank=True)
    contract_type = models.ForeignKey(ContractType, on_delete=models.CASCADE, null=True, blank=True)
    contract_type_text = models.CharField(max_length=255, null=True, blank=True)
    award_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    due_date_late = models.BooleanField(null=True, blank=True)
    sales_class = models.ForeignKey(SalesClass, on_delete=models.CASCADE, null=True, blank=True)
    sales_class_text = models.CharField(max_length=255, null=True, blank=True)
    nist = models.BooleanField(null=True, blank=True)
    files_url = models.CharField(max_length=200, null=True, blank=True)
    contract_value = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    planned_split = models.CharField(max_length=50, null=True, blank=True)
    plan_gross = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)

    # Processing Fields
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    queue_id = models.IntegerField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_process_contracts')
    modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='modified_process_contracts')
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    # Final Contract Reference (after processing)
    final_contract = models.ForeignKey(Contract, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Processing Contract'
        verbose_name_plural = 'Processing Contracts'

    def __str__(self):
        return f"Processing Contract: {self.contract_number}"

    def save(self, *args, **kwargs):
        if not self.company_id:
            self.company = Company.get_default_company()
        super().save(*args, **kwargs)

    def calculate_contract_value(self):
        """Calculate contract value by summing all CLIN item values"""
        total = self.clins.aggregate(
            total=models.Sum('item_value', default=Decimal('0.00'))
        )['total']
        return total

    def calculate_plan_gross(self):
        """Calculate plan gross by subtracting total quote values from contract value"""
        totals = self.clins.aggregate(
            item_total=models.Sum('item_value', default=Decimal('0.00')),
            quote_total=models.Sum('quote_value', default=Decimal('0.00'))
        )
        return totals['item_total'] - totals['quote_total']

    def update_calculated_values(self):
        """Update contract value and plan gross"""
        self.contract_value = self.calculate_contract_value()
        self.plan_gross = self.calculate_plan_gross()
        self.save()

    @property
    def total_split_value(self):
        from django.db.models import Sum
        return (
            ProcessClinSplit.objects.filter(
                clin__process_contract=self
            ).aggregate(total=Sum('split_value'))['total'] or 0
        )

    @property
    def total_split_paid(self):
        from django.db.models import Sum
        return (
            ProcessClinSplit.objects.filter(
                clin__process_contract=self
            ).aggregate(total=Sum('split_paid'))['total'] or 0
        )

class ProcessClin(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('ready_for_review', 'Ready for Review'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    ORIGIN_DESTINATION_CHOICES = [
        ('O', 'Origin'),
        ('D', 'Destination'),
    ]
    
    ITEM_TYPE_CHOICES = [
        ('P', 'Production'),
        ('G', 'GFAT'),
        ('C', 'CFAT'),
        ('L', 'PLT'),
        ('M', 'Miscellaneous')
    ]

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='processing_clins', null=False, blank=True)
    process_contract = models.ForeignKey(ProcessContract, on_delete=models.CASCADE, null=True, blank=True, related_name='clins')
    item_number = models.CharField(max_length=20, null=True, blank=True)
    item_type = models.CharField(max_length=20, null=True, blank=True, choices=ITEM_TYPE_CHOICES)
    item_value = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    po_num_ext = models.CharField(max_length=5, null=True, blank=True)
    tab_num = models.CharField(max_length=10, null=True, blank=True)
    clin_po_num = models.CharField(max_length=10, null=True, blank=True)
    po_number = models.CharField(max_length=10, null=True, blank=True)
    clin_type = models.ForeignKey(ClinType, on_delete=models.CASCADE, null=True, blank=True)
    clin_type_text = models.CharField(max_length=255, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, null=True, blank=True)
    supplier_text = models.CharField(max_length=255, null=True, blank=True)
    nsn = models.ForeignKey(Nsn, on_delete=models.CASCADE, null=True, blank=True)
    nsn_text = models.CharField(max_length=255, null=True, blank=True)
    nsn_description_text = models.CharField(max_length=255, null=True, blank=True)
    ia = models.CharField(max_length=5, null=True, blank=True, choices=ORIGIN_DESTINATION_CHOICES)
    fob = models.CharField(max_length=5, null=True, blank=True, choices=ORIGIN_DESTINATION_CHOICES)
    description = models.TextField(null=True, blank=True)
    order_qty = models.FloatField(null=True, blank=True)
    uom = models.CharField(max_length=10, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    due_date_late = models.BooleanField(null=True, blank=True)
    supplier_due_date = models.DateField(null=True, blank=True)
    supplier_due_date_late = models.BooleanField(null=True, blank=True)

    # CLIN_Finance
    special_payment_terms = models.ForeignKey(SpecialPaymentTerms, on_delete=models.CASCADE, null=True, blank=True)
    special_payment_terms_text = models.CharField(max_length=255, null=True, blank=True)
    special_payment_terms_paid = models.BooleanField(null=True, blank=True)
    price_per_unit = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    quote_value = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    special_payment_terms_interest = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    special_payment_terms_party = models.CharField(max_length=50, null=True, blank=True)

    # Processing Fields
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    # Final CLIN Reference (after processing)
    final_clin = models.ForeignKey(Clin, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['item_number']
        verbose_name = 'Processing CLIN'
        verbose_name_plural = 'Processing CLINs'

    def __str__(self):
        contract_number = self.process_contract.contract_number if self.process_contract else 'No Contract'
        return f"Processing CLIN: {self.item_number} for {contract_number}"

    def save(self, *args, **kwargs):
        if not self.company_id:
            if self.process_contract and self.process_contract.company_id:
                self.company_id = self.process_contract.company_id
            else:
                self.company = Company.get_default_company()
        super().save(*args, **kwargs)


class ProcessClinSplit(models.Model):
    """Staging split row for a process CLIN; materialized to contracts.ClinSplit on finalization."""
    clin = models.ForeignKey(ProcessClin, on_delete=models.CASCADE, related_name='splits')
    company_name = models.CharField(max_length=100)
    split_value = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    split_paid = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company_name']
        verbose_name = 'Process CLIN Split'
        verbose_name_plural = 'Process CLIN Splits'
        db_table = 'processing_processclin_split'

    def __str__(self):
        item = self.clin.item_number or self.clin_id
        return f"{self.company_name} (CLIN {item})"

    @classmethod
    def create_split(cls, process_clin_id, company_name, split_value, split_paid=None):
        """Create a new ProcessClinSplit for the given process CLIN."""
        ProcessClinModel = cls._meta.get_field('clin').related_model
        try:
            process_clin = ProcessClinModel.objects.get(pk=process_clin_id)
        except ProcessClinModel.DoesNotExist:
            raise ValueError(f"ProcessClin with id '{process_clin_id}' does not exist.")
        if not company_name:
            raise ValueError("Company name cannot be empty.")
        if split_value is None:
            raise ValueError("Split value cannot be None.")
        paid = split_paid
        if paid is None:
            paid = Decimal('0.00')
        row = cls(
            clin=process_clin,
            company_name=company_name,
            split_value=split_value,
            split_paid=paid,
        )
        row.save()
        return row

    @classmethod
    def update_split(cls, split_id, company_name=None, split_value=None, split_paid=None):
        """Update an existing ProcessClinSplit row."""
        try:
            row = cls.objects.get(pk=split_id)
        except cls.DoesNotExist:
            raise ValueError(f"ProcessClinSplit with id '{split_id}' does not exist.")
        if company_name is not None:
            row.company_name = company_name
        if split_value is not None:
            row.split_value = split_value
        if split_paid is not None:
            row.split_paid = split_paid
        row.save()
        return row

    @classmethod
    def delete_split(cls, split_id):
        """Delete a ProcessClinSplit by primary key."""
        try:
            row = cls.objects.get(pk=split_id)
            row.delete()
            return True
        except cls.DoesNotExist:
            return False
