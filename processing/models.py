from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
from contracts.models import (
    AuditModel, Buyer, Nsn, Supplier, ContractType, Contract, 
    Clin, IdiqContract, SalesClass, ClinType, SpecialPaymentTerms
)

class QueueContract(AuditModel):
    """Model for storing queued contracts before they become live contracts"""
    contract_number = models.CharField(max_length=25, null=True, blank=True)
    buyer = models.CharField(max_length=255, null=True, blank=True)  # String value to be matched later
    award_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    contract_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    contract_type = models.CharField(max_length=50, null=True, blank=True)  # Unilateral, Bilateral, IDIQ
    solicitation_type = models.CharField(max_length=50, null=True, blank=True, default='SDVOSB')
    
    # Status tracking
    is_being_processed = models.BooleanField(default=False)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processing_contracts')
    processing_started = models.DateTimeField(null=True, blank=True)
    
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

class QueueClin(AuditModel):
    """Model for storing queued CLINs before they become live CLINs"""
    contract_queue = models.ForeignKey(QueueContract, on_delete=models.CASCADE, related_name='clins')
    item_number = models.CharField(max_length=20, null=True, blank=True)
    item_type = models.CharField(max_length=20, null=True, blank=True)  # FAT, PVT, Production
    nsn = models.CharField(max_length=20, null=True, blank=True)  # String value to be matched later
    nsn_description = models.TextField(null=True, blank=True)
    ia = models.CharField(max_length=5, null=True, blank=True, choices=[('O', 'Origin'), ('D', 'Destination')])
    fob = models.CharField(max_length=5, null=True, blank=True, choices=[('O', 'Origin'), ('D', 'Destination')])
    due_date = models.DateField(null=True, blank=True)
    order_qty = models.FloatField(null=True, blank=True)
    item_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    
    # Optional supplier information
    supplier = models.CharField(max_length=255, null=True, blank=True)  # String value to be matched later
    supplier_due_date = models.DateField(null=True, blank=True)
    supplier_unit_price = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    supplier_price = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
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

    idiq_contract = models.ForeignKey(IdiqContract, on_delete=models.CASCADE, null=True, blank=True)
    contract_number = models.CharField(max_length=25, null=True, blank=True, unique=True)
    solicitation_type = models.CharField(max_length=10, null=True, blank=True, default='SDVOSB')
    po_number = models.CharField(max_length=10, null=True, blank=True)
    tab_num = models.CharField(max_length=10, null=True, blank=True)
    buyer = models.ForeignKey(Buyer, on_delete=models.CASCADE, null=True, blank=True)
    buyer_text = models.CharField(max_length=255, null=True, blank=True)
    contract_type = models.ForeignKey(ContractType, on_delete=models.CASCADE, null=True, blank=True)
    award_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    due_date_late = models.BooleanField(null=True, blank=True)
    sales_class = models.ForeignKey(SalesClass, on_delete=models.CASCADE, null=True, blank=True)
    nist = models.BooleanField(null=True, blank=True)
    files_url = models.CharField(max_length=200, null=True, blank=True)
    contract_value = models.FloatField(null=True, blank=True, default=0)
    description = models.TextField(null=True, blank=True)
    planned_split = models.CharField(max_length=50, null=True, blank=True)
    ppi_split = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    statz_split = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    ppi_split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    statz_split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)

    # Processing Fields
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    queue_id = models.IntegerField()  # Reference to original queue item
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

    process_contract = models.ForeignKey(ProcessContract, on_delete=models.CASCADE, null=True, blank=True, related_name='clins')
    item_number = models.CharField(max_length=20, null=True, blank=True)
    item_type = models.CharField(max_length=20, null=True, blank=True, choices=ITEM_TYPE_CHOICES)
    item_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    po_num_ext = models.CharField(max_length=5, null=True, blank=True)
    tab_num = models.CharField(max_length=10, null=True, blank=True)
    clin_po_num = models.CharField(max_length=10, null=True, blank=True)
    po_number = models.CharField(max_length=10, null=True, blank=True)
    clin_type = models.ForeignKey(ClinType, on_delete=models.CASCADE, null=True, blank=True)
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
    special_payment_terms_paid = models.BooleanField(null=True, blank=True)
    price_per_unit = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    quote_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    plan_gross = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    planned_split = models.CharField(max_length=50, null=True, blank=True)
    ppi_split = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    statz_split = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    ppi_split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    statz_split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    special_payment_terms_interest = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
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
        return f"Processing CLIN: {self.item_number} for {self.process_contract.contract_number}"
