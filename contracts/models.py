from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.conf import settings

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
    idiq_contract = models.ForeignKey('IdiqContract', on_delete=models.CASCADE, null=True, blank=True)
    contract_number = models.CharField(max_length=25, null=True, blank=True, unique=True)
    status = models.ForeignKey('ContractStatus', on_delete=models.CASCADE, null=True, blank=True)
    solicitation_type = models.CharField(max_length=10, null=True, blank=True, default='SDVOSB')
    open = models.BooleanField(null=True, blank=True)
    date_closed = models.DateTimeField(null=True, blank=True)
    cancelled = models.BooleanField(null=True, blank=True)
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
    ppi_split = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    statz_split = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    ppi_split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    statz_split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)

    class Meta:
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
            models.Index(fields=['po_number'], name='contract_po_number_idx'),
            models.Index(fields=['tab_num'], name='contract_tab_num_idx'),
            models.Index(fields=['open'], name='contract_open_idx'),
            models.Index(fields=['cancelled'], name='contract_cancelled_idx'),
            models.Index(fields=['due_date'], name='contract_due_idx'),
            models.Index(fields=['award_date'], name='contract_award_idx'),
            models.Index(fields=['assigned_user'], name='contract_assigned_idx'),
            
            # Compound indexes for common query patterns
            models.Index(fields=['open', 'due_date'], name='contract_open_due_idx'),
            models.Index(fields=['status', 'due_date'], name='contract_status_due_idx'),
            models.Index(fields=['due_date_late'], name='contract_due_late_idx'),
            models.Index(fields=['reviewed'], name='contract_reviewed_idx'),
        ]

    def __str__(self):
        return f"Contract {self.contract_number}"
    
class ContractStatus(models.Model):
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.description

class Clin(AuditModel):
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
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE, null=True, blank=True)
    nsn = models.ForeignKey('Nsn', on_delete=models.CASCADE, null=True, blank=True)
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

    # CLIN_Finance
    special_payment_terms = models.ForeignKey('SpecialPaymentTerms', on_delete=models.CASCADE, null=True, blank=True) # Moved to Contract
    special_payment_terms_paid = models.BooleanField(null=True, blank=True) # Moved to Contract
    price_per_unit = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True) # data maps to PPP_Sup
    quote_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True) # Possible name change to quote_value? this is being populated with contract value
    paid_amount = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    wawf_payment = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    wawf_recieved = models.DateTimeField(null=True, blank=True)
    wawf_invoice = models.CharField(max_length=25, null=True, blank=True)
    plan_gross = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    planned_split = models.CharField(max_length=50, null=True, blank=True)
    ppi_split = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    statz_split = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    ppi_split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    statz_split_paid = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    special_payment_terms_interest = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    special_payment_terms_party = models.CharField(max_length=50, null=True, blank=True)


    class Meta:
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
        return f"CLIN {self.id} for Contract {self.contract.contract_number}"


class PaymentHistory(models.Model):
    PAYMENT_TYPE_CHOICES = [
        ('item_value', 'Item Value'),  # SubPO
        ('quote_value', 'Quote Value'), # 2
        ('paid_amount', 'Paid Amount'), # SubPaid
        ('contract_value', 'Contract Value'), # Contract
        ('wawf_payment', 'WAWF Payment'), # WAWFPayment
        ('plan_gross', 'Plan Gross'), # PlanGross
        ('statz_split_paid', 'STATZ Split Paid'), # PaidPPI
        ('ppi_split_paid', 'PPI Split Paid'), # PaidSTATZ
        ('special_payment_terms_interest', 'Special Payment Terms Interest'), # Interest
    ]

    clin = models.ForeignKey(Clin, on_delete=models.CASCADE, related_name='payment_history')
    payment_type = models.CharField(max_length=50, choices=PAYMENT_TYPE_CHOICES)
    payment_amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    payment_date = models.DateField()
    payment_info = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_history_created_by')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_history_updated_by')

    def __str__(self):
        return f"{self.clin} - {self.payment_type} - {self.payment_amount}"

    class Meta:
        ordering = ['-payment_date', '-created_at']
        verbose_name_plural = 'Payment histories'

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
    nsn = models.ForeignKey('Nsn', on_delete=models.CASCADE)
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE)

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


class Nsn(AuditModel):
    nsn_code = models.CharField(max_length=20, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    part_number = models.CharField(max_length=25, null=True, blank=True)
    revision = models.CharField(max_length=25, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    directory_url = models.CharField(max_length=200, null=True, blank=True)

    def __str__(self):
        return f"NSN {self.nsn_code}"


class Supplier(AuditModel):
    name = models.CharField(max_length=100, null=True, blank=True)
    cage_code = models.CharField(max_length=10, null=True, blank=True)
    supplier_type = models.ForeignKey('SupplierType', on_delete=models.CASCADE, null=True, blank=True)
    billing_address = models.ForeignKey('Address', on_delete=models.CASCADE, null=True, blank=True, related_name='supplier_billing')
    shipping_address = models.ForeignKey('Address', on_delete=models.CASCADE, null=True, blank=True, related_name='supplier_shipping')
    physical_address = models.ForeignKey('Address', on_delete=models.CASCADE, null=True, blank=True, related_name='supplier_physical')
    business_phone = models.CharField(max_length=25, null=True, blank=True)
    business_fax = models.CharField(max_length=25, null=True, blank=True)
    business_email = models.EmailField(null=True, blank=True)
    contact = models.ForeignKey('Contact', on_delete=models.CASCADE, null=True, blank=True)
    probation = models.BooleanField(null=True, blank=True)
    probation_on = models.DateTimeField(null=True, blank=True)
    probation_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='supplier_probation')
    conditional = models.BooleanField(null=True, blank=True)
    conditional_on = models.DateTimeField(null=True, blank=True)
    conditional_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='supplier_conditional')
    special_terms = models.ForeignKey('SpecialPaymentTerms', on_delete=models.CASCADE, null=True, blank=True)
    special_terms_on = models.DateTimeField(null=True, blank=True)
    prime = models.IntegerField(null=True, blank=True)
    ppi = models.BooleanField(null=True, blank=True)
    iso = models.BooleanField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    is_packhouse = models.BooleanField(null=True, blank=True)
    packhouse = models.ForeignKey('Supplier', on_delete=models.CASCADE, null=True, blank=True)
    files_url = models.CharField(max_length=200, null=True, blank=True)
    allows_gsi = models.BooleanField(null=True, blank=True)

    def __str__(self):
        name_display = self.name.upper() if self.name else "NO NAME"
        cage_code_display = self.cage_code if self.cage_code else ""
        return f"{name_display}{' - ' + cage_code_display if cage_code_display else ''}"


class SupplierType(models.Model):
    code = models.CharField(max_length=1, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.description


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

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"Note for {self.content_type.name} {self.object_id}"
    


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

class Contact(models.Model):
    SALUTATION_CHOICES = [
        ('Mr.', 'Mr.'),
        ('Mrs.', 'Mrs.'),
        ('Ms.', 'Ms.'),
        ('Dr.', 'Dr.'),
        ('Prof.', 'Prof.'),
        ('', 'None'),
    ]
    
    salutation = models.CharField(max_length=5, choices=SALUTATION_CHOICES, blank=True, default='')
    name = models.TextField()
    company = models.TextField(null=True, blank=True)
    title = models.TextField(null=True, blank=True)
    phone = models.CharField(max_length=25, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    address = models.ForeignKey('Address', on_delete=models.CASCADE, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name


class SupplierCertification(models.Model):
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE)
    certification_type = models.ForeignKey('CertificationType', on_delete=models.CASCADE)
    certification_date = models.DateTimeField(null=True, blank=True)
    certification_expiration = models.DateTimeField(null=True, blank=True)
    compliance_status = models.CharField(max_length=25, null=True, blank=True, default=None)

    def __str__(self):
        return f"{self.supplier.name} - {self.certification_type.name}"


class CertificationType(models.Model):
    code = models.CharField(max_length=25, null=True, blank=True)
    name = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name
        

class SupplierClassification(models.Model):
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE)
    classification_type = models.ForeignKey('ClassificationType', on_delete=models.CASCADE)
    classification_date = models.DateTimeField(null=True, blank=True)
    classification_expiration = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.supplier.name} - {self.classification_type.name}"

class ClassificationType(models.Model):
    name = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name
    
class Reminder(models.Model):
    reminder_title = models.CharField(max_length=50, null=True, blank=True)
    reminder_text = models.TextField(null=True, blank=True)
    reminder_date = models.DateTimeField(null=True, blank=True)
    reminder_user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='created_reminders')
    reminder_completed = models.BooleanField(null=True, blank=True)
    reminder_completed_date = models.DateTimeField(null=True, blank=True)
    reminder_completed_user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='completed_reminders')
    note = models.ForeignKey('Note', on_delete=models.CASCADE, null=True, blank=True, related_name='note_reminders')
    
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

class ClinView(models.Model):
    """
    A database view model for optimized CLIN data retrieval.
    This model represents a SQL view that joins CLIN data with related tables
    to provide faster access to commonly needed CLIN information.
    
    Note: This is a read-only model that maps to a database view.
    """
    id = models.IntegerField(primary_key=True)
    contract_id = models.IntegerField(null=True)
    item_number = models.CharField(max_length=20, null=True)  # This is the Item Number of the CLIN 0001, 0002, etc.
    item_type = models.CharField(max_length=20, null=True)  # This is the Type of CLIN (Production, GFAT, CFAT, PLT)
    item_value = models.DecimalField(max_digits=19, decimal_places=4, null=True)  # This is the Value in $ for the CLIN
    contract_number = models.CharField(max_length=25, null=True)
    clin_po_num = models.CharField(max_length=10, null=True)
    po_number = models.CharField(max_length=10, null=True)
    po_num_ext = models.CharField(max_length=5, null=True)
    tab_num = models.CharField(max_length=10, null=True)
    
    clin_type_id = models.IntegerField(null=True)
    clin_type_description = models.TextField(null=True)
    
    supplier_id = models.IntegerField(null=True)
    supplier_name = models.CharField(max_length=100, null=True)
    supplier_cage_code = models.CharField(max_length=10, null=True)
    
    nsn_id = models.IntegerField(null=True)
    nsn_code = models.CharField(max_length=20, null=True)
    nsn_description = models.TextField(null=True)
    
    ia = models.CharField(max_length=5, null=True)
    fob = models.CharField(max_length=5, null=True)
    order_qty = models.FloatField(null=True)
    ship_qty = models.FloatField(null=True)
    
    due_date = models.DateField(null=True)
    due_date_late = models.BooleanField(null=True)
    supplier_due_date = models.DateField(null=True)
    supplier_due_date_late = models.BooleanField(null=True)
    ship_date = models.DateField(null=True)
    ship_date_late = models.BooleanField(null=True)
    
    special_payment_terms_id = models.IntegerField(null=True)
    special_payment_terms_code = models.CharField(max_length=5, null=True)
    special_payment_terms_description = models.CharField(max_length=30, null=True)
    special_payment_terms_paid = models.BooleanField(null=True)
    
    quote_value = models.DecimalField(max_digits=19, decimal_places=4, null=True)
    paid_amount = models.DecimalField(max_digits=19, decimal_places=4, null=True)
    
    created_by_id = models.IntegerField(null=True)
    created_by_username = models.CharField(max_length=150, null=True)
    created_on = models.DateTimeField(null=True)
    modified_by_id = models.IntegerField(null=True)
    modified_by_username = models.CharField(max_length=150, null=True)
    modified_on = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = 'clin_view'

    def __str__(self):
        return f"CLIN View {self.id} - {self.clin_po_num or 'Unknown'}"

class NsnView(models.Model):
    """
    A database view model for optimized NSN data retrieval.
    This model represents a SQL view that joins NSN data with related information
    including a count of associated CLINs and a concatenated search vector for text search.
    
    Note: This is a read-only model that maps to a database view.
    """
    id = models.IntegerField(primary_key=True)
    nsn_code = models.CharField(max_length=20, null=True)
    description = models.TextField(null=True)
    part_number = models.CharField(max_length=25, null=True)
    revision = models.CharField(max_length=25, null=True)
    notes = models.TextField(null=True)
    directory_url = models.CharField(max_length=200, null=True)
    
    # Count of CLINs using this NSN (computed in the view)
    clin_count = models.IntegerField(null=True)
    
    # Concatenated field for text search optimization
    search_vector = models.TextField(null=True)
    
    class Meta:
        managed = False
        db_table = 'nsn_view'
        indexes = [
            models.Index(fields=['nsn_code'], name='nsn_view_code_idx'),
            # Note: search_vector cannot be indexed directly in SQL Server as it's NVARCHAR(MAX)
        ]

    def __str__(self):
        return f"NSN {self.nsn_code}"


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

