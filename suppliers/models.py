from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class AuditModel(models.Model):
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='suppliers_%(class)s_created',
    )
    created_on = models.DateTimeField(default=timezone.now)
    modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='suppliers_%(class)s_modified',
    )
    modified_on = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.id:
            self.created_on = timezone.now()
        self.modified_on = timezone.now()
        super().save(*args, **kwargs)


class Supplier(AuditModel):
    name = models.CharField(max_length=100, null=True, blank=True)
    cage_code = models.CharField(max_length=10, null=True, blank=True)
    dodaac = models.CharField(max_length=10, null=True, blank=True)
    supplier_type = models.ForeignKey('SupplierType', on_delete=models.CASCADE, null=True, blank=True)
    billing_address = models.ForeignKey('contracts.Address', on_delete=models.CASCADE, null=True, blank=True, related_name='supplier_billing')
    shipping_address = models.ForeignKey('contracts.Address', on_delete=models.CASCADE, null=True, blank=True, related_name='supplier_shipping')
    physical_address = models.ForeignKey('contracts.Address', on_delete=models.CASCADE, null=True, blank=True, related_name='supplier_physical')
    business_phone = models.CharField(max_length=25, null=True, blank=True)
    business_fax = models.CharField(max_length=25, null=True, blank=True)
    business_email = models.EmailField(null=True, blank=True)
    website_url = models.URLField(null=True, blank=True)
    primary_phone = models.CharField(max_length=50, null=True, blank=True)
    primary_email = models.EmailField(null=True, blank=True)
    logo_url = models.URLField(null=True, blank=True)
    last_enriched_at = models.DateTimeField(null=True, blank=True)
    contact = models.ForeignKey('Contact', on_delete=models.CASCADE, null=True, blank=True, related_name='primary_for_supplier')
    probation = models.BooleanField(null=True, blank=True)
    probation_on = models.DateTimeField(null=True, blank=True)
    probation_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='suppliers_supplier_probation')
    conditional = models.BooleanField(null=True, blank=True)
    conditional_on = models.DateTimeField(null=True, blank=True)
    conditional_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='suppliers_supplier_conditional')
    special_terms = models.ForeignKey('contracts.SpecialPaymentTerms', on_delete=models.CASCADE, null=True, blank=True)
    special_terms_on = models.DateTimeField(null=True, blank=True)
    prime = models.IntegerField(null=True, blank=True)
    ppi = models.BooleanField(null=True, blank=True)
    iso = models.BooleanField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    is_packhouse = models.BooleanField(null=True, blank=True)
    packhouse = models.ForeignKey('Supplier', on_delete=models.CASCADE, null=True, blank=True)
    files_url = models.CharField(max_length=400, null=True, blank=True)
    ALLOWS_GSI_CHOICES = [
        ('UNK', 'Unknown'),
        ('YES', 'Yes'),
        ('NO', 'No'),
    ]
    allows_gsi = models.CharField(
        max_length=3,
        choices=ALLOWS_GSI_CHOICES,
        default='UNK',
        help_text="Whether the supplier allows GSI at facility (Unknown until confirmed).",
    )
    archived = models.BooleanField(default=False)
    archived_on = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='suppliers_supplier_archived')

    class Meta:
        db_table = 'contracts_supplier'

    def __str__(self):
        name_display = self.name.upper() if self.name else "NO NAME"
        cage_code_display = self.cage_code if self.cage_code else ""
        return f"{name_display}{' - ' + cage_code_display if cage_code_display else ''}"


class SupplierType(models.Model):
    code = models.CharField(max_length=1, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_suppliertype'

    def __str__(self):
        return self.description


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
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE, null=True, blank=True, related_name='contacts')
    address = models.ForeignKey('contracts.Address', on_delete=models.CASCADE, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_contact'

    def __str__(self):
        return self.name


class SupplierCertification(models.Model):
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE)
    certification_type = models.ForeignKey('CertificationType', on_delete=models.CASCADE)
    certification_date = models.DateTimeField(null=True, blank=True)
    certification_expiration = models.DateTimeField(null=True, blank=True)
    compliance_status = models.CharField(max_length=25, null=True, blank=True, default=None)

    class Meta:
        db_table = 'contracts_suppliercertification'

    def __str__(self):
        return f"{self.supplier.name} - {self.certification_type.name}"


class CertificationType(models.Model):
    code = models.CharField(max_length=25, null=True, blank=True)
    name = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_certificationtype'

    def __str__(self):
        return self.name


class SupplierClassification(models.Model):
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE)
    classification_type = models.ForeignKey('ClassificationType', on_delete=models.CASCADE)
    classification_date = models.DateTimeField(null=True, blank=True)
    classification_expiration = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_supplierclassification'

    def __str__(self):
        return f"{self.supplier.name} - {self.classification_type.name}"


class ClassificationType(models.Model):
    name = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'contracts_classificationtype'

    def __str__(self):
        return self.name


class SupplierDocument(AuditModel):
    DOC_TYPE_CHOICES = [
        ('CERT', 'Certification'),
        ('CLASS', 'Classification'),
        ('GENERAL', 'General'),
    ]

    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE, related_name='documents')
    certification = models.ForeignKey('SupplierCertification', on_delete=models.CASCADE, null=True, blank=True, related_name='documents')
    classification = models.ForeignKey('SupplierClassification', on_delete=models.CASCADE, null=True, blank=True, related_name='documents')
    doc_type = models.CharField(max_length=12, choices=DOC_TYPE_CHOICES, default='GENERAL')
    description = models.CharField(max_length=255, null=True, blank=True)
    file = models.FileField(upload_to='supplier-docs/')

    class Meta:
        db_table = 'contracts_supplierdocument'

    def __str__(self):
        label = self.get_doc_type_display() or 'Document'
        return f"{label} for {self.supplier.name if self.supplier else 'Unknown'}"
