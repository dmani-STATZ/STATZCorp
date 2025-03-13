from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.db.models.signals import pre_save
from django.dispatch import receiver

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
    special_payment_terms = models.ForeignKey('SpecialPaymentTerms', on_delete=models.CASCADE, null=True, blank=True)
    special_payment_terms_paid = models.BooleanField(null=True, blank=True)
    price_per_unit = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    clin_value = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True) # Possible name change to clin_value?
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
        return f"{self.name.upper()} - {self.cage_code}"


class SupplierType(models.Model):
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
    


class AcknowledgementLetter(AuditModel):
    clin = models.ForeignKey(Clin, on_delete=models.CASCADE)
    letter_date = models.DateTimeField(null=True, blank=True)
    salutation = models.TextField(null=True, blank=True)
    addr_fname = models.TextField(null=True, blank=True)
    addr_lname = models.TextField(null=True, blank=True)
    supplier = models.TextField(null=True, blank=True)
    st_address = models.TextField(null=True, blank=True)
    city = models.TextField(null=True, blank=True)
    state = models.TextField(null=True, blank=True)
    zip = models.CharField(max_length=10, null=True, blank=True)
    po = models.CharField(max_length=10, null=True, blank=True)
    po_ext = models.CharField(max_length=5, null=True, blank=True)
    contract_num = models.CharField(max_length=25, null=True, blank=True)
    fat_plt_due_date = models.DateTimeField(null=True, blank=True)
    supplier_due_date = models.DateTimeField(null=True, blank=True)
    dpas_priority = models.CharField(max_length=50, null=True, blank=True)
    statz_contact = models.TextField(null=True, blank=True)
    statz_contact_title = models.TextField(null=True, blank=True)
    statz_contact_phone = models.CharField(max_length=25, null=True, blank=True)
    statz_contact_email = models.EmailField(null=True, blank=True)

    def __str__(self):
        return f"Acknowledgement Letter for CLIN {self.clin.id}"

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
    compliance_status = models.ForeignKey('CertificationStatus', on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"{self.supplier.name} - {self.certification_type.name}"


class CertificationType(models.Model):
    code = models.CharField(max_length=25, null=True, blank=True)
    name = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name
    

class CertificationStatus(models.Model):
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

class SequenceNumber(models.Model):
    """Model to store and manage auto-incrementing sequence numbers"""
    po_number = models.BigIntegerField(default=10000)  # Starting value
    tab_number = models.BigIntegerField(default=10000)  # Starting value
    
    @classmethod
    def get_po_number(cls):
        """Get the next PO number and increment the stored value"""
        sequence, created = cls.objects.get_or_create(id=1)
        current_po = sequence.po_number
        return str(current_po)
    
    @classmethod
    def get_tab_number(cls):
        """Get the next TAB number and increment the stored value"""
        sequence, created = cls.objects.get_or_create(id=1)
        current_tab = sequence.tab_number
        return str(current_tab)
    
    @classmethod
    def advance_po_number(cls):
        sequence, created = cls.objects.get_or_create(id=1)
        sequence.po_number += 1
        sequence.save()
    
    @classmethod
    def advance_tab_number(cls):
        sequence, created = cls.objects.get_or_create(id=1)
        sequence.tab_number += 1
        sequence.save()
    
@receiver(pre_save, sender=Contract)
def assign_po_tab_numbers(sender, instance, **kwargs):
    """Assign PO and TAB numbers to new contracts if they don't already have them"""
    if not instance.pk:  # Only for new contracts
        if not instance.po_number:
            instance.po_number = SequenceNumber.get_po_number()
            SequenceNumber.advance_po_number()
        if not instance.tab_num:
            instance.tab_num = SequenceNumber.get_tab_number()
            SequenceNumber.advance_tab_number()

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
    
    clin_value = models.DecimalField(max_digits=19, decimal_places=4, null=True)
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
