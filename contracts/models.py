from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.db.models.signals import pre_save
from django.db.models import Sum
from django.dispatch import receiver
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.conf import settings

from products.models import Nsn
from suppliers.models import Supplier


class Company(models.Model):
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    logo = models.FileField(upload_to='company-logos/', null=True, blank=True)
    primary_color = models.CharField(max_length=7, null=True, blank=True, help_text="Hex color like #004eb3")
    secondary_color = models.CharField(max_length=7, null=True, blank=True, help_text="Hex color like #e5e7eb")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "company"
            slug = base_slug
            index = 1
            while Company.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                index += 1
                slug = f"{base_slug}-{index}"
            self.slug = slug
        super().save(*args, **kwargs)

    @classmethod
    def get_default_company(cls):
        company, _ = cls.objects.get_or_create(
            slug="company-a",
            defaults={"name": "Company A", "is_active": True},
        )
        return company

    @property
    def logo_url(self):
        try:
            return self.logo.url if self.logo else None
        except Exception:
            return None

    def get_primary_color(self):
        return self.primary_color or "#004eb3"

    def get_secondary_color(self):
        return self.secondary_color or "#e5e7eb"

class AuditModel(models.Model):
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='%(class)s_created')
    created_on = models.DateTimeField(default=timezone.now)
    modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='%(class)s_modified')
    modified_on = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.id:
            self.created_on = timezone.now()
        self.modified_on = timezone.now()
        super().save(*args, **kwargs)

class Contract(AuditModel):
    company = models.ForeignKey('Company', on_delete=models.PROTECT, related_name='contracts', null=False, blank=True)
    idiq_contract = models.ForeignKey('IdiqContract', on_delete=models.CASCADE, null=True, blank=True)
    contract_number = models.CharField(max_length=25, null=True, blank=True, unique=True)
    status = models.ForeignKey('ContractStatus', on_delete=models.CASCADE, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True)
    solicitation_type = models.CharField(max_length=10, null=True, blank=True, default='SDVOSB')
    prime = models.CharField(max_length=25, null=True, blank=True)
    prime_po_number = models.CharField(max_length=10, null=True, blank=True)
    date_closed = models.DateTimeField(null=True, blank=True)
    date_canceled = models.DateTimeField(null=True, blank=True)
    canceled_reason = models.ForeignKey('CanceledReason', on_delete=models.CASCADE, null=True, blank=True)
    po_number = models.CharField(max_length=10, null=True, blank=True) # maybe part of clin?
    tab_num = models.CharField(max_length=10, null=True, blank=True)  # maybe part of clin?
    buyer = models.ForeignKey('Buyer', on_delete=models.CASCADE, null=True, blank=True)
    contract_type = models.ForeignKey('ContractType', on_delete=models.CASCADE, null=True, blank=True)
    award_date = models.DateTimeField(null=True, blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    due_date_late = models.BooleanField(null=True, blank=True)
    sales_class = models.ForeignKey('SalesClass', on_delete=models.CASCADE, null=True, blank=True)
    survey_date = models.DateField(null=True, blank=True)
    survey_type = models.CharField(max_length=10, null=True, blank=True)
    assigned_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='contract_assigned_user')
    assigned_date = models.DateTimeField(null=True, blank=True)
    nist = models.BooleanField(null=True, blank=True)
    files_url = models.CharField(max_length=200, null=True, blank=True)
    reviewed = models.BooleanField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='contract_reviewed_by')
    reviewed_on = models.DateTimeField(null=True, blank=True)
    notes = GenericRelation('Note', related_query_name='contract')
    contract_value = models.FloatField(null=True, blank=True, default=0)
    planned_split = models.CharField(max_length=50, null=True, blank=True)
    plan_gross = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    # Contract-level Special Payment Terms (single source of truth)
    special_payment_terms = models.ForeignKey('SpecialPaymentTerms', on_delete=models.CASCADE, null=True, blank=True)
    payment_history = GenericRelation('PaymentHistory', related_query_name='contract')

    class Meta:
        db_table = 'contracts_contract'
        indexes = [
            # Foreign key indexes
            models.Index(fields=['idiq_contract'], name='contract_idiq_idx'),
            models.Index(fields=['status'], name='contract_status_idx'),
            models.Index(fields=['canceled_reason'], name='contract_cancel_reason_idx'),
            models.Index(fields=['buyer'], name='contract_buyer_idx'),
            models.Index(fields=['contract_type'], name='contract_type_idx'),
            models.Index(fields=['sales_class'], name='contract_sales_idx'),
            
            # Common search/filter fields
            models.Index(fields=['contract_number'], name='contract_number_idx'),
            models.Index(fields=['prime'], name='contract_prime_idx'),
            models.Index(fields=['prime_po_number'], name='contract_prime_po_number_idx'),
            models.Index(fields=['po_number'], name='contract_po_number_idx'),
            models.Index(fields=['tab_num'], name='contract_tab_num_idx'),
            models.Index(fields=['due_date'], name='contract_due_idx'),
            models.Index(fields=['award_date'], name='contract_award_idx'),
            models.Index(fields=['assigned_user'], name='contract_assigned_idx'),
            
            # Compound indexes for common query patterns
            models.Index(fields=['status', 'due_date'], name='contract_status_due_idx'),
            models.Index(fields=['due_date_late'], name='contract_due_late_idx'),
            models.Index(fields=['reviewed'], name='contract_reviewed_idx'),
        ]

    def __str__(self):
        return f"Contract {self.contract_number}"

    def save(self, *args, **kwargs):
        if not self.company_id:
            self.company = Company.get_default_company()
        super().save(*args, **kwargs)
    
    @property
    def total_split_value(self):
        return self.splits.aggregate(Sum('split_value'))['split_value__sum'] or 0
    
    @property
    def total_split_paid(self):
        return self.splits.aggregate(Sum('split_paid'))['split_paid__sum'] or 0

    def get_sharepoint_documents_url(self):
        """
        Build SharePoint folder URL for this contract's documents.
        Uses V87/aFed-DOD path; Closed/Cancelled contracts use Closed Contracts subfolder.
        Returns None if contract_number is missing.
        """
        from urllib.parse import quote
        if not self.contract_number:
            return None
        base = 'https://statzcorpgcch.sharepoint.us/sites/Statz/Shared%20Documents/Forms/AllItems.aspx'
        root = '/sites/Statz/Shared Documents/Statz-Public/data/V87/aFed-DOD'
        status_desc = (self.status.description or '').strip() if self.status else ''
        if status_desc in ('Closed', 'Cancelled'):
            path = f'{root}/Closed Contracts/Contract {self.contract_number}'
        else:
            path = f'{root}/Contract {self.contract_number}'
        viewid = 'd4837fde%2D32f5%2D41cc%2Db723%2D09d5f692b2ea'
        return f'{base}?id={quote(path)}&viewid={viewid}'


class ContractStatus(models.Model):
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.description

class Clin(AuditModel):
    company = models.ForeignKey('Company', on_delete=models.PROTECT, related_name='clins', null=False, blank=True)
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

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, null=True, blank=True)
    item_number = models.CharField(max_length=20, null=True, blank=True) # This is the Item Number of the CLIN 0001, 0002, etc.
    item_type = models.CharField(max_length=20, null=True, blank=True, choices=ITEM_TYPE_CHOICES) # This is the Type of CLIN (Production, GFAT, CFAT, PLT)  
    item_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True) # This is the Value in $ for the CLIN
    unit_price = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True) # This is the Unit Price in $ for the CLIN Data maps to PPP_Cont
    po_num_ext = models.CharField(max_length=5, null=True, blank=True) # What do we use this for?
    tab_num = models.CharField(max_length=10, null=True, blank=True)
    clin_po_num = models.CharField(max_length=10, null=True, blank=True) # What do we use this for?
    po_number = models.CharField(max_length=10, null=True, blank=True) # What do we use this for?
    clin_type = models.ForeignKey('ClinType', on_delete=models.CASCADE, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, null=True, blank=True)
    nsn = models.ForeignKey(Nsn, on_delete=models.PROTECT, null=True, blank=True)
    ia = models.CharField(max_length=5, null=True, blank=True, choices=ORIGIN_DESTINATION_CHOICES) #Should this be two fields?
    fob = models.CharField(max_length=5, null=True, blank=True, choices=ORIGIN_DESTINATION_CHOICES)
    order_qty = models.FloatField(null=True, blank=True)
    uom = models.CharField(max_length=10, null=True, blank=True)
    ship_qty = models.FloatField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    due_date_late = models.BooleanField(null=True, blank=True)
    supplier_due_date = models.DateField(null=True, blank=True)
    supplier_due_date_late = models.BooleanField(null=True, blank=True)
    ship_date = models.DateField(null=True, blank=True)
    ship_date_late = models.BooleanField(null=True, blank=True)
    notes = GenericRelation('Note', related_query_name='clin')
    payment_history = GenericRelation('PaymentHistory', related_query_name='clin')

    # CLIN_Finance
    special_payment_terms = models.ForeignKey('SpecialPaymentTerms', on_delete=models.CASCADE, null=True, blank=True) # Moved to Contract
    special_payment_terms_paid = models.BooleanField(null=True, blank=True) # Moved to Contract
    price_per_unit = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True) # data maps to PPP_Sup
    quote_value = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True) # Possible name change to quote_value? this is being populated with contract value
    paid_amount = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    wawf_payment = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    wawf_recieved = models.DateTimeField(null=True, blank=True)
    wawf_invoice = models.CharField(max_length=25, null=True, blank=True)
    special_payment_terms_interest = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    special_payment_terms_party = models.CharField(max_length=50, null=True, blank=True)

    # Log Fields (from old Gov Actions / Log section)
    log_status = models.TextField(null=True, blank=True)
    log_notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_clin'
        indexes = [
            # Foreign key indexes
            models.Index(fields=['contract'], name='clin_contract_idx'),
            models.Index(fields=['clin_type'], name='clin_type_idx'),
            models.Index(fields=['supplier'], name='clin_supplier_idx'),
            models.Index(fields=['nsn'], name='clin_nsn_idx'),
            models.Index(fields=['special_payment_terms'], name='clin_payment_terms_idx'),
            
            # Common search/filter fields
            models.Index(fields=['po_number'], name='clin_po_number_idx'),
            models.Index(fields=['tab_num'], name='clin_tab_num_idx'),
            models.Index(fields=['due_date'], name='clin_due_date_idx'),
            models.Index(fields=['supplier_due_date'], name='clin_supp_due_date_idx'),
            models.Index(fields=['ship_date'], name='clin_ship_date_idx'),
            
            # Compound indexes for common query patterns
            models.Index(fields=['contract', 'due_date'], name='clin_contract_due_idx'),
            models.Index(fields=['supplier', 'due_date'], name='clin_supp_due_idx'),
            models.Index(fields=['due_date_late'], name='clin_due_late_idx'),
            models.Index(fields=['supplier_due_date_late'], name='clin_supp_due_late_idx'),
            models.Index(fields=['ship_date_late'], name='clin_ship_late_idx'),
        ]

    def __str__(self):
        contract_number = self.contract.contract_number if self.contract else 'No Contract'
        return f"CLIN {self.id} for Contract {contract_number}"

    def save(self, *args, **kwargs):
        if not self.company_id:
            if self.contract and self.contract.company_id:
                self.company_id = self.contract.company_id
            else:
                self.company = Company.get_default_company()
        super().save(*args, **kwargs)
    
    @property
    def total_shipped(self):
        return self.shipments.aggregate(Sum('ship_qty'))['ship_qty__sum'] or 0

class ClinShipment(AuditModel):
    """
    Model for tracking individual shipments for a CLIN.
    Allows multiple shipments to be recorded against a single CLIN.
    """
    clin = models.ForeignKey(Clin, on_delete=models.CASCADE, related_name='shipments')
    ship_qty = models.FloatField(null=True, blank=True)
    uom = models.CharField(max_length=10, null=True, blank=True)  # Unit of Measure
    ship_date = models.DateField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-ship_date', '-created_on']
        indexes = [
            models.Index(fields=['clin'], name='clinship_clin_idx'),
            models.Index(fields=['ship_date'], name='clinship_date_idx'),
            # Compound index for common query patterns
            models.Index(fields=['clin', 'ship_date'], name='clinship_clin_date_idx'),
        ]

    def __str__(self):
        return f"Shipment of {self.ship_qty} {self.uom} on {self.ship_date} for CLIN {self.clin.id}"

class PaymentHistory(AuditModel):
    """
    Model for tracking payment history for both Contracts and CLINs.
    Uses ContentType framework to allow generic relations to different models.
    """
    PAYMENT_TYPE_CHOICES = [
        # Contract-level payment types
        ('contract_value', 'Contract Value'),
        ('plan_gross', 'Plan Gross'),
        
        # CLIN-level payment types
        ('item_value', 'Item Value'),
        ('quote_value', 'Quote Value'),
        ('paid_amount', 'Paid Amount'),
        ('wawf_payment', 'WAWF Payment'),
    ]

    # Generic relation fields
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    # Payment details
    payment_type = models.CharField(max_length=50, choices=PAYMENT_TYPE_CHOICES)
    payment_amount = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    payment_date = models.DateField()
    payment_info = models.TextField(blank=True, null=True)
    reference_number = models.CharField(max_length=50, blank=True, null=True)
    
    class Meta:
        ordering = ['-payment_date', '-created_on']
        verbose_name_plural = 'Payment histories'
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['payment_type']),
            models.Index(fields=['payment_date']),
        ]

    def __str__(self):
        return f"{self.content_object} - {self.get_payment_type_display()} - {self.payment_amount}"

    @property
    def entity_type(self):
        """Returns the type of entity this payment is associated with (e.g., 'contract' or 'clin')"""
        return self.content_type.model

    @classmethod
    def get_contract_payment_types(cls):
        """Returns payment types that are valid for contracts"""
        return [
            'contract_value',
            'plan_gross',
        ]

    @classmethod
    def get_clin_payment_types(cls):
        """Returns payment types that are valid for CLINs"""
        return [
            'item_value',
            'quote_value',
            'paid_amount',
            'wawf_payment',
        ]

    def clean(self):
        """Validates that the payment type is appropriate for the content object"""
        if self.content_type.model == 'contract' and self.payment_type not in self.get_contract_payment_types():
            raise ValidationError({
                'payment_type': f'Payment type {self.get_payment_type_display()} is not valid for contracts'
            })
        elif self.content_type.model == 'clin' and self.payment_type not in self.get_clin_payment_types():
            raise ValidationError({
                'payment_type': f'Payment type {self.get_payment_type_display()} is not valid for CLINs'
            })
        super().clean()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

class IdiqContract(AuditModel):
    contract_number = models.CharField(max_length=50, null=True, blank=True)
    buyer = models.ForeignKey('Buyer', on_delete=models.CASCADE, null=True, blank=True)
    award_date = models.DateTimeField(null=True, blank=True)
    term_length = models.IntegerField(null=True, blank=True)
    option_length = models.IntegerField(null=True, blank=True)
    closed = models.BooleanField(null=True, blank=True)
    tab_num = models.CharField(max_length=10, null=True, blank=True)
    notes = GenericRelation('Note', related_query_name='idiq_contract')

    class Meta:
        indexes = [
            # Foreign key indexes
            models.Index(fields=['buyer'], name='idiq_buyer_idx'),
            
            # Common search/filter fields
            models.Index(fields=['contract_number'], name='idiq_contract_num_idx'),
            models.Index(fields=['tab_num'], name='idiq_tab_num_idx'),
            models.Index(fields=['award_date'], name='idiq_award_idx'),
            models.Index(fields=['closed'], name='idiq_closed_idx'),
        ]

    def __str__(self):
        return f"IDIQ Contract {self.contract_number}"


class IdiqContractDetails(models.Model):
    idiq_contract = models.ForeignKey(IdiqContract, on_delete=models.CASCADE)
    nsn = models.ForeignKey(Nsn, on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=['idiq_contract'], name='idiq_details_contract_idx'),
            models.Index(fields=['nsn'], name='idiq_details_nsn_idx'),
            models.Index(fields=['supplier'], name='idiq_details_supplier_idx'),
            # Compound index for common query pattern
            models.Index(fields=['idiq_contract', 'nsn'], name='idiq_details_contract_nsn_idx'),
        ]

    def __str__(self):
        return f"Details for IDIQ Contract {self.idiq_contract.contract_number}"


class SpecialPaymentTerms(models.Model):
    code = models.CharField(max_length=5, null=True, blank=True)
    terms = models.CharField(max_length=30)

    def __str__(self):
        return self.terms


class Buyer(models.Model):
    description = models.TextField(null=True, blank=True)
    address = models.ForeignKey('Address', on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.description

class ContractType(models.Model):
    description = models.TextField(null=True, blank=True)


    def __str__(self):
        return self.description

class ClinType(models.Model):
    description = models.TextField(null=True, blank=True)
    raw_text = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.description

class CanceledReason(models.Model):
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.description

class SalesClass(models.Model):
    sales_team = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.sales_team

class Note(AuditModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    note = models.TextField(null=True, blank=True)
    company = models.ForeignKey('Company', on_delete=models.PROTECT, null=True, blank=True, related_name='notes')

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"Note for {self.content_type.name} {self.object_id}"

    def save(self, *args, **kwargs):
        if not self.company_id and self.content_object is not None and hasattr(self.content_object, 'company_id'):
            self.company_id = getattr(self.content_object, 'company_id', None)
        super().save(*args, **kwargs)
    


class AcknowledgementLetter(models.Model):
    SALUTATION_CHOICES = [
        ('Mr.', 'Mr.'),
        ('Mrs.', 'Mrs.'),
        ('Ms.', 'Ms.'),
        ('Dr.', 'Dr.'),
        ('Prof.', 'Prof.'),
        ('', 'None'),
    ]

    clin = models.ForeignKey('Clin', on_delete=models.CASCADE)
    letter_date = models.DateField(null=True, blank=True)
    salutation = models.CharField(max_length=10, choices=SALUTATION_CHOICES, null=True, blank=True)
    addr_fname = models.CharField(max_length=50, null=True, blank=True)
    addr_lname = models.CharField(max_length=50, null=True, blank=True)
    supplier = models.CharField(max_length=100, null=True, blank=True)
    st_address = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=50, null=True, blank=True)
    state = models.CharField(max_length=20, null=True, blank=True)
    zip = models.CharField(max_length=10, null=True, blank=True)
    po = models.CharField(max_length=50, null=True, blank=True)
    po_ext = models.CharField(max_length=10, null=True, blank=True)
    contract_num = models.CharField(max_length=50, null=True, blank=True)
    statz_contact = models.CharField(max_length=100, null=True, blank=True)
    statz_contact_title = models.CharField(max_length=50, null=True, blank=True)
    statz_contact_phone = models.CharField(max_length=20, null=True, blank=True)
    statz_contact_email = models.EmailField(null=True, blank=True)
    fat_plt_due_date = models.DateField(null=True, blank=True)
    supplier_due_date = models.DateField(null=True, blank=True)
    dpas_priority = models.CharField(max_length=10, null=True, blank=True)
    created_on = models.DateTimeField(auto_now_add=True)
    modified_on = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='acknowledgement_letters_created')
    modified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='acknowledgement_letters_modified')

    class Meta:
        ordering = ['-modified_on']
        verbose_name = 'Acknowledgement Letter'
        verbose_name_plural = 'Acknowledgement Letters'

    def __str__(self):
        return f'Acknowledgement Letter for CLIN {self.clin.id} - {self.letter_date}'

class ClinAcknowledgment(AuditModel):
    clin = models.ForeignKey(Clin, on_delete=models.CASCADE)
    po_to_supplier_bool = models.BooleanField(null=True, blank=True)
    po_to_supplier_date = models.DateTimeField(null=True, blank=True)
    po_to_supplier_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='clin_acknowledgment_po_to_supplier')
    clin_reply_bool = models.BooleanField(null=True, blank=True)
    clin_reply_date = models.DateTimeField(null=True, blank=True)
    clin_reply_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='clin_acknowledgment_clin_reply')
    po_to_qar_bool = models.BooleanField(null=True, blank=True)
    po_to_qar_date = models.DateTimeField(null=True, blank=True)
    po_to_qar_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='clin_acknowledgment_po_to_qar')

    def __str__(self):
        return f"Acknowledgment for CLIN {self.clin.id}"


class GovAction(AuditModel):
    """Gov Actions linked to Contract (PAR, RFV, ECP, QN, NCR tracking)."""
    ACTION_CHOICES = [
        ('PAR', 'PAR'),
        ('RFV', 'RFV'),
        ('ECP', 'ECP'),
        ('QN', 'QN'),
        ('NCR', 'NCR'),
    ]
    REQUEST_CHOICES = [
        ('Admin', 'Admin'),
        ('Technical', 'Technical'),
        ('Extension', 'Extension'),
        ('Cancellation', 'Cancellation'),
        ('Qty Change', 'Qty Change'),
        ('Litigation', 'Litigation'),
        ('Price', 'Price'),
        ('Other', 'Other'),
    ]
    INITIATED_CHOICES = [
        ('STATZ', 'STATZ'),
        ('Gov', 'Gov'),
        ('Supplier', 'Supplier'),
    ]
    company = models.ForeignKey('Company', on_delete=models.PROTECT, null=True, blank=True, related_name='gov_actions')
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='gov_actions')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, null=True, blank=True)
    number = models.CharField(max_length=50, null=True, blank=True)
    request = models.CharField(max_length=30, choices=REQUEST_CHOICES, null=True, blank=True)
    date_submitted = models.DateField(null=True, blank=True)
    date_closed = models.DateField(null=True, blank=True)
    initiated = models.CharField(max_length=20, choices=INITIATED_CHOICES, null=True, blank=True)

    class Meta:
        db_table = 'contracts_govaction'
        ordering = ['-date_submitted', '-created_on']
        verbose_name = 'Gov Action'
        verbose_name_plural = 'Gov Actions'

    def __str__(self):
        return f"{self.get_action_display() or self.action} {self.number or ''} - {self.contract.contract_number}"

    def save(self, *args, **kwargs):
        if not self.company_id and self.contract_id:
            self.company_id = self.contract.company_id
        super().save(*args, **kwargs)


class Address(models.Model):
    address_line_1 = models.TextField(null=True, blank=True)
    address_line_2 = models.TextField(null=True, blank=True)
    city = models.TextField(null=True, blank=True)
    state = models.TextField(null=True, blank=True)
    zip = models.CharField(max_length=15, null=True, blank=True)

    def __str__(self):
        # Create a list of address components, filtering out None values
        address_parts = [
            self.address_line_1 or '',
            self.address_line_2 or '',
            self.city or '',
            self.state or '',
            self.zip or ''
        ]
        # Join non-empty parts with spaces
        return ' '.join(part for part in address_parts if part)

class Reminder(models.Model):
    reminder_title = models.CharField(max_length=50, null=True, blank=True)
    reminder_text = models.TextField(null=True, blank=True)
    reminder_date = models.DateTimeField(null=True, blank=True)
    reminder_user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='created_reminders')
    reminder_completed = models.BooleanField(null=True, blank=True)
    reminder_completed_date = models.DateTimeField(null=True, blank=True)
    reminder_completed_user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='completed_reminders')
    note = models.ForeignKey('Note', on_delete=models.CASCADE, null=True, blank=True, related_name='note_reminders')
    company = models.ForeignKey('Company', on_delete=models.PROTECT, null=True, blank=True, related_name='reminders')
    
    class Meta:
        indexes = [
            models.Index(fields=["note"]),
        ]

    def __str__(self):
        note_type = "Standalone"
        if self.note:
            content_type = self.note.content_type.model
            object_id = self.note.object_id
            note_type = f"Note for {content_type.capitalize()} {object_id}"
        return f"{self.reminder_title} - {self.reminder_date.strftime('%Y-%m-%d') if self.reminder_date else 'No date'} ({note_type})"

class Expedite(models.Model):
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE)
    initiated = models.BooleanField(null=True, blank=True, default=False)
    initiateddate = models.DateTimeField(null=True, blank=True)
    initiatedby = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='expedite_initiated')
    successful = models.BooleanField(null=True, blank=True, default=False)
    successfuldate = models.DateTimeField(null=True, blank=True)
    successfulby = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='expedite_successful')
    used = models.BooleanField(null=True, blank=True, default=False)
    useddate = models.DateTimeField(null=True, blank=True)
    usedby = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='expedite_used')
    
    class Meta:
        indexes = [
            models.Index(fields=['contract']),
        ]

    def __str__(self):
        return f"Expedite {self.contract.contract_number}"

class FolderStack(models.Model):
    name = models.CharField(max_length=20)
    description = models.TextField(null=True, blank=True)
    color = models.CharField(max_length=20)
    order = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class FolderTracking(AuditModel):
    STACK_CHOICES = [
        ('0 - NONE', 'NONE'),
        ('1 - COS', 'COS'),
        ('2 - PACK', 'PACK'),
        ('3 - PROCESS', 'PROCESS'),
        ('4 - W4QAR', 'W4QAR'),
        ('5 - W4BOL', 'W4BOL'),
        ('6 - W4POS', 'W4POS'),
        ('7 - W4POD', 'W4POD'),
        ('8 - W4PAY', 'W4PAY'),
        ('9 - QSIGN', 'QSIGN'),
        ('10 - PAID', 'PAID'),
    ]

    STACK_COLORS = {
        '0 - NONE': 'white',
        '1 - COS': 'gold',
        '2 - PACK': 'blue',
        '3 - PROCESS': 'lightblue',
        '4 - W4QAR': 'yellow',
        '5 - W4BOL': 'green',
        '6 - W4POS': 'salmon',
        '7 - W4POD': 'lavender',
        '8 - W4PAY': 'grey',
        '9 - QSIGN': 'teal',
        '10 - PAID': 'red',
    }

    # Visible Fields
    stack_id = models.ForeignKey('FolderStack', on_delete=models.CASCADE, related_name='folder_tracking')
    stack = models.CharField(max_length=20, choices=STACK_CHOICES)
    contract = models.ForeignKey('Contract', on_delete=models.CASCADE, related_name='folder_tracking')
    partial = models.CharField(max_length=20, null=True, blank=True)
    rts_email = models.BooleanField(default=False)
    qb_inv = models.CharField(max_length=10, null=True, blank=True)
    wawf = models.BooleanField(default=False)
    wawf_qar = models.BooleanField(default=False)
    vsm_scn = models.CharField(max_length=20, null=True, blank=True)
    sir_scn = models.CharField(max_length=20, null=True, blank=True)
    tracking = models.CharField(max_length=20, null=True, blank=True)
    tracking_number = models.CharField(max_length=20, null=True, blank=True)
    sort_data = models.CharField(max_length=20, null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    highlight = models.BooleanField(default=False)

    # Behind the scenes fields
    closed = models.BooleanField(default=False)
    date_added = models.DateTimeField(auto_now_add=True)
    date_closed = models.DateTimeField(null=True, blank=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='folder_tracking_added')
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='folder_tracking_closed')

    class Meta:
        indexes = [
            models.Index(fields=['contract'], name='fld_track_contract_idx'),
            models.Index(fields=['stack'], name='fld_track_stack_idx'),
            models.Index(fields=['closed'], name='fld_track_closed_idx'),
            models.Index(fields=['date_added'], name='fld_track_added_idx'),
            models.Index(fields=['date_closed'], name='fld_track_dclosed_idx'),
            # Compound indexes for common query patterns
            models.Index(fields=['contract', 'stack'], name='fld_track_con_stack_idx'),
            models.Index(fields=['closed', 'stack'], name='fld_track_cls_stack_idx'),
        ]

    def __str__(self):
        return f"Folder Tracking - {self.contract.contract_number} ({self.stack})"

    @property
    def stack_color(self):
        return self.STACK_COLORS.get(self.stack, '')

    def close_record(self, user):
        """
        Close the record instead of deleting it
        """
        self.closed = True
        self.date_closed = timezone.now()
        self.closed_by = user
        self.modified_by = user
        self.save()

    def toggle_highlight(self, user):
        """
        Toggle the highlight status of the record
        """
        self.highlight = not self.highlight
        self.modified_by = user
        self.save()

class ExportTiming(models.Model):
    row_count = models.IntegerField()
    export_time = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)
    filters_applied = models.JSONField(default=dict)

    @classmethod
    def get_estimated_time(cls, row_count):
        """
        Get estimated export time based on historical data.
        Uses weighted average of recent exports, giving more weight to:
        1. More recent exports
        2. Exports with similar row counts
        3. Exports with similar filters
        """
        if row_count <= 0:
            return 1  # Minimum 1 second for empty exports
            
        # Get the last 10 export timings, ordered by most recent
        recent_timings = cls.objects.order_by('-timestamp')[:10]
        
        if not recent_timings:
            # If no historical data, use a conservative estimate
            return max(1, row_count * 0.015)  # Base estimate of 15ms per row
            
        total_weight = 0
        weighted_time_per_row = 0
        
        for timing in recent_timings:
            # Calculate time per row for this export
            time_per_row = timing.export_time / timing.row_count if timing.row_count > 0 else 0
            
            # Calculate weights based on different factors
            recency_weight = 1.0  # Most recent entries get full weight
            if timing.timestamp:
                # Reduce weight for older entries (weight reduces by 10% per day, minimum 0.1)
                days_old = (timezone.now() - timing.timestamp).days
                recency_weight = max(0.1, 1.0 - (days_old * 0.1))
            
            # Size similarity weight (1.0 for exact match, decreasing as difference increases)
            size_ratio = min(timing.row_count, row_count) / max(timing.row_count, row_count)
            size_weight = size_ratio ** 2  # Square to emphasize similarity
            
            # Combine weights
            total_weight_this_entry = recency_weight * size_weight
            
            weighted_time_per_row += time_per_row * total_weight_this_entry
            total_weight += total_weight_this_entry
        
        # Calculate final weighted average time per row
        avg_time_per_row = (
            weighted_time_per_row / total_weight if total_weight > 0 
            else 0.015  # Default to 15ms per row if weights sum to 0
        )
        
        # Add 10% buffer for safety
        estimated_time = (avg_time_per_row * row_count) * 1.1
        
        # Ensure minimum of 1 second
        return max(1, estimated_time)

class ContractSplit(models.Model):
    """Model for storing dynamic contract splits between different companies"""
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='splits')
    company_name = models.CharField(max_length=100)
    split_value = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    split_paid = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['company_name']
        verbose_name = 'Contract Split'
        verbose_name_plural = 'Contract Splits'
        db_table = 'contracts_contractsplit'

    def __str__(self):
        return f"{self.company_name} Split for {self.contract.contract_number}"
    
   
    @classmethod
    def create_split(cls, contract_id, company_name, split_value, split_paid=0.00):
        """Creates a new ContractSplit record."""
        try:
            contract = cls._meta.get_field('contract').related_model.objects.get(pk=contract_id)
        except cls._meta.get_field('contract').related_model.DoesNotExist:
            raise ValueError(f"Contract with id '{contract_id}' does not exist.")

        if not company_name:
            raise ValueError("Company name cannot be empty.")
        if split_value is None:
            raise ValueError("Split value cannot be None.")

        contract_split = cls(
            contract=contract,
            company_name=company_name,
            split_value=split_value,
            split_paid=split_paid,
        )
        contract_split.save()
        return contract_split

    @classmethod
    def update_split(cls, contract_split_id, company_name=None, split_value=None, split_paid=None):
        """Updates an existing ContractSplit record."""
        try:
            contract_split = cls.objects.get(pk=contract_split_id)
        except cls.DoesNotExist:
            raise ValueError(f"ContractSplit with id '{contract_split_id}' does not exist.")

        if company_name is not None:
            contract_split.company_name = company_name
        if split_value is not None:
            contract_split.split_value = split_value
        if split_paid is not None:
            contract_split.split_paid = split_paid

        contract_split.modified_at = timezone.now()
        contract_split.save()
        return contract_split

    @classmethod
    def delete_split(cls, contract_split_id):
        """Deletes a ContractSplit record."""
        try:
            contract_split = cls.objects.get(pk=contract_split_id)
            contract_split.delete()
            return True  # Indicate successful deletion
        except cls.DoesNotExist:
            return False # Indicate record not found
