from django.db import models

class Contract(models.Model):
    contract_number = models.CharField(max_length=25)
    open = models.BooleanField()
    date_closed = models.DateTimeField(null=True, blank=True)
    cancelled = models.BooleanField()
    date_canceled = models.DateTimeField(null=True, blank=True)
    canceled_reason = models.ForeignKey('CanceledReason', on_delete=models.CASCADE)
    po_number = models.CharField(max_length=10)
    tab_num = models.CharField(max_length=10)
    buyer = models.ForeignKey('Buyer', on_delete=models.CASCADE)
    contract_type = models.ForeignKey('ContractType', on_delete=models.CASCADE)
    award_date = models.DateTimeField()
    due_date = models.DateTimeField()
    due_date_late = models.BooleanField()
    sales_class = models.ForeignKey('SalesClass', on_delete=models.CASCADE)
    survey_date = models.DateField()
    survey_type = models.CharField(max_length=10)
    assigned_user = models.CharField(max_length=20)
    assigned_date = models.DateTimeField()
    nist = models.BooleanField()
    files_url = models.CharField(max_length=200)
    reviewed = models.BooleanField()
    reviewed_by = models.CharField(max_length=20, null=True, blank=True)
    reviewed_on = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Contract {self.contract_number}"

class Clin(models.Model):
    clin_finance = models.OneToOneField('ClinFinance', on_delete=models.CASCADE)
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE)
    sub_contract = models.CharField(max_length=20, null=True, blank=True)
    po_num_ext = models.CharField(max_length=5, null=True, blank=True)
    tab_num = models.CharField(max_length=10, null=True, blank=True)
    clin_po_num = models.CharField(max_length=10, null=True, blank=True)
    po_number = models.CharField(max_length=10, null=True, blank=True)
    clin_type = models.ForeignKey('ClinType', on_delete=models.CASCADE)
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE)
    nsn = models.ForeignKey('Nsn', on_delete=models.CASCADE)
    ia = models.CharField(max_length=5, null=True, blank=True)
    fob = models.CharField(max_length=5, null=True, blank=True)
    order_qty = models.FloatField()
    ship_qty = models.FloatField()
    due_date = models.DateField()
    due_date_late = models.BooleanField()
    supplier_due_date = models.DateField(null=True, blank=True)
    supplier_due_date_late = models.BooleanField()
    ship_date = models.DateField(null=True, blank=True)
    ship_date_late = models.BooleanField()

    def __str__(self):
        return f"CLIN {self.id} for Contract {self.contract.contract_number}"

class IdiqContract(models.Model):
    contract_number = models.CharField(max_length=50)
    buyer = models.ForeignKey('Buyer', on_delete=models.CASCADE)
    award_date = models.DateTimeField()
    term_length = models.IntegerField()
    option_length = models.IntegerField()
    closed = models.BooleanField()

    def __str__(self):
        return f"IDIQ Contract {self.contract_number}"

class IdiqContractToContract(models.Model):
    idiq_contract = models.ForeignKey(IdiqContract, on_delete=models.CASCADE)
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE)

    def __str__(self):
        return f"IDIQ Contract {self.idiq_contract.contract_number} to Contract {self.contract.contract_number}"

class IdiqContractDetails(models.Model):
    idiq_contract = models.ForeignKey(IdiqContract, on_delete=models.CASCADE)
    nsn = models.ForeignKey('Nsn', on_delete=models.CASCADE)
    supplier = models.ForeignKey('Supplier', on_delete=models.CASCADE)

    def __str__(self):
        return f"Details for IDIQ Contract {self.idiq_contract.contract_number}"

class ClinFinance(models.Model):
    special_payment_terms = models.ForeignKey('SpecialPaymentTerms', on_delete=models.CASCADE)
    special_payment_terms_paid = models.BooleanField()
    contract_value = models.DecimalField(max_digits=19, decimal_places=4)
    po_amount = models.DecimalField(max_digits=19, decimal_places=4)
    paid_amount = models.DecimalField(max_digits=19, decimal_places=4)
    paid_date = models.DateTimeField(null=True, blank=True)
    wawf_payment = models.DecimalField(max_digits=19, decimal_places=4)
    wawf_recieved = models.DateTimeField(null=True, blank=True)
    wawf_invoice = models.CharField(max_length=25, null=True, blank=True)
    plan_gross = models.DecimalField(max_digits=19, decimal_places=4)
    planned_split = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"Finance for CLIN {self.id}"

class SpecialPaymentTerms(models.Model):
    terms = models.CharField(max_length=30)

    def __str__(self):
        return self.terms

class Nsn(models.Model):
    nsn_code = models.IntegerField()
    description = models.TextField()

    def __str__(self):
        return f"NSN {self.nsn_code}"

class Supplier(models.Model):
    name = models.TextField()
    cage_code = models.IntegerField()
    supplier_type = models.ForeignKey('SupplierType', on_delete=models.CASCADE)

    def __str__(self):
        return self.name

class SupplierType(models.Model):
    description = models.TextField()

    def __str__(self):
        return self.description

class Buyer(models.Model):
    description = models.TextField()

    def __str__(self):
        return self.description

class ContractType(models.Model):
    description = models.TextField()

    def __str__(self):
        return self.description

class ClinType(models.Model):
    description = models.TextField()

    def __str__(self):
        return self.description

class CanceledReason(models.Model):
    description = models.TextField()

    def __str__(self):
        return self.description

class SalesClass(models.Model):
    sales_team = models.TextField()

    def __str__(self):
        return self.sales_team

class ContractNote(models.Model):
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE)
    note = models.TextField()
    created_by = models.TextField()
    created_on = models.DateTimeField()

    def __str__(self):
        return f"Note for Contract {self.contract.contract_number}"

class ClinNote(models.Model):
    clin = models.ForeignKey(Clin, on_delete=models.CASCADE)
    note = models.TextField()
    created_by = models.TextField()
    created_on = models.DateTimeField()

    def __str__(self):
        return f"Note for CLIN {self.clin.id}"

class AcknowledgementLetter(models.Model):
    clin = models.ForeignKey(Clin, on_delete=models.CASCADE)
    letter_date = models.DateTimeField()
    salutation = models.TextField()
    addr_fname = models.TextField()
    addr_lname = models.TextField()
    supplier = models.TextField()
    st_address = models.TextField()
    city = models.TextField()
    state = models.TextField()
    zip = models.IntegerField()
    po = models.IntegerField()
    po_ext = models.IntegerField()
    contract_num = models.IntegerField()
    fat_plt_due_date = models.DateTimeField()
    supplier_due_date = models.DateTimeField()
    dpas_priority = models.IntegerField()
    statz_contact = models.TextField()
    statz_contact_title = models.TextField()
    statz_contact_phone = models.IntegerField()
    statz_contact_email = models.EmailField()

    def __str__(self):
        return f"Acknowledgement Letter for CLIN {self.clin.id}"

class ClinAcknowledgment(models.Model):
    clin = models.ForeignKey(Clin, on_delete=models.CASCADE)
    po_to_supplier_bool = models.BooleanField()
    po_to_supplier_date = models.DateTimeField()
    po_to_supplier_user = models.TextField()
    clin_reply_bool = models.BooleanField()
    clin_reply_date = models.DateTimeField()
    clin_reply_user = models.TextField()

    def __str__(self):
        return f"Acknowledgment for CLIN {self.clin.id}"
