# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class StatzAcknowledgmentTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    subid = models.IntegerField(db_column='SubID', unique=True)  # Field name made lowercase.
    potosub_bool = models.BooleanField(db_column='POtoSub_Bool')  # Field name made lowercase.
    potosub_date = models.DateTimeField(db_column='POtoSub_Date', blank=True, null=True)  # Field name made lowercase.
    potosub_user = models.CharField(db_column='POtoSub_User', max_length=50, blank=True, null=True)  # Field name made lowercase.
    subreply_bool = models.BooleanField(db_column='SubReply_Bool')  # Field name made lowercase.
    subreply_date = models.DateTimeField(db_column='SubReply_Date', blank=True, null=True)  # Field name made lowercase.
    subreply_user = models.CharField(db_column='SubReply_User', max_length=50, blank=True, null=True)  # Field name made lowercase.
    potoqar_bool = models.BooleanField(db_column='POtoQAR_Bool')  # Field name made lowercase.
    potoqar_date = models.DateTimeField(db_column='POtoQAR_Date', blank=True, null=True)  # Field name made lowercase.
    potoqar_user = models.CharField(db_column='POtoQAR_User', max_length=50, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_ACKNOWLEDGMENT_TBL'


class StatzAckLetterFormatTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    page1_title = models.CharField(db_column='Page1_TITLE', max_length=255, blank=True, null=True)  # Field name made lowercase.
    page1 = models.TextField(db_column='Page1', blank=True, null=True)  # Field name made lowercase.
    page2_title = models.CharField(db_column='Page2_TITLE', max_length=255, blank=True, null=True)  # Field name made lowercase.
    page2 = models.TextField(db_column='Page2', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_ACK_LETTER_FORMAT_TBL'


class StatzAckLetterTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    contract_id = models.IntegerField(db_column='Contract_ID', blank=True, null=True)  # Field name made lowercase.
    subid = models.IntegerField(db_column='SubID', unique=True)  # Field name made lowercase.
    letter_date = models.DateTimeField(db_column='LETTER DATE', blank=True, null=True)  # Field name made lowercase. Field renamed to remove unsuitable characters.
    salutation = models.CharField(db_column='SALUTATION', max_length=50, blank=True, null=True)  # Field name made lowercase.
    addr_fname = models.CharField(db_column='ADDR_FNAME', max_length=50, blank=True, null=True)  # Field name made lowercase.
    addr_lname = models.CharField(db_column='ADDR_LNAME', max_length=50, blank=True, null=True)  # Field name made lowercase.
    vendor = models.CharField(db_column='Vendor', max_length=100, blank=True, null=True)  # Field name made lowercase.
    st_address = models.CharField(db_column='ST_ADDRESS', max_length=100, blank=True, null=True)  # Field name made lowercase.
    city = models.CharField(db_column='CITY', max_length=50, blank=True, null=True)  # Field name made lowercase.
    state = models.CharField(db_column='STATE', max_length=50, blank=True, null=True)  # Field name made lowercase.
    zip = models.CharField(db_column='ZIP', max_length=50, blank=True, null=True)  # Field name made lowercase.
    po = models.CharField(db_column='PO', max_length=10, blank=True, null=True)  # Field name made lowercase.
    po_ext = models.CharField(db_column='PO_ext', max_length=50, blank=True, null=True)  # Field name made lowercase.
    contractnum = models.CharField(db_column='ContractNum', max_length=50, blank=True, null=True)  # Field name made lowercase.
    fat_pltduedate = models.DateTimeField(db_column='FAT_PLTDueDate', blank=True, null=True)  # Field name made lowercase.
    vendorduedate = models.DateField(db_column='VendorDueDate', blank=True, null=True)  # Field name made lowercase.
    dpaspriority = models.CharField(db_column='DPASPriority', max_length=50, blank=True, null=True)  # Field name made lowercase.
    statzcontact = models.CharField(db_column='StatzContact', max_length=50, blank=True, null=True)  # Field name made lowercase.
    statzcontacttitle = models.CharField(db_column='StatzContactTitle', max_length=50, blank=True, null=True)  # Field name made lowercase.
    statzcontactphone = models.CharField(db_column='StatzContactPhone', max_length=50, blank=True, null=True)  # Field name made lowercase.
    statzcontactemail = models.CharField(db_column='StatzContactEmail', max_length=50, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_ACK_LETTER_TBL'


class StatzActivity2Tbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    rowversion = models.TextField(db_column='RowVersion')  # Field name made lowercase. This field type is a guess.
    username = models.CharField(db_column='UserName', max_length=50)  # Field name made lowercase.
    firstactive = models.DateTimeField(db_column='FirstActive')  # Field name made lowercase.
    lastactive = models.DateTimeField(db_column='LastActive')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_ACTIVITY2_TBL'


class StatzActivityLogTbl(models.Model):
    id = models.CharField(db_column='ID', primary_key=True, max_length=36)  # Field name made lowercase.
    category = models.CharField(db_column='Category', max_length=50, blank=True, null=True)  # Field name made lowercase.
    activity = models.CharField(db_column='Activity', max_length=255, blank=True, null=True)  # Field name made lowercase.
    activityinfo = models.TextField(db_column='ActivityInfo', blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=50, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_ACTIVITY_LOG_TBL'


class StatzActivityTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    rowversion = models.TextField(db_column='RowVersion')  # Field name made lowercase. This field type is a guess.
    username = models.CharField(db_column='UserName', max_length=50)  # Field name made lowercase.
    computername = models.CharField(db_column='ComputerName', max_length=50)  # Field name made lowercase.
    loginout = models.BooleanField(db_column='LogInOut')  # Field name made lowercase.
    loginouttime = models.DateTimeField(db_column='LogInOutTime')  # Field name made lowercase.
    logintime = models.DateTimeField(db_column='LogInTime', blank=True, null=True)  # Field name made lowercase.
    logouttime = models.DateTimeField(db_column='LogOutTime', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_ACTIVITY_TBL'


class StatzBidPartsbaseDlaTbl(models.Model):
    genid = models.CharField(db_column='GenID', primary_key=True, max_length=36)  # Field name made lowercase.
    request = models.CharField(db_column='Request', max_length=255)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    niin = models.CharField(db_column='NIIN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    fsc = models.CharField(db_column='FSC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    inc = models.CharField(db_column='INC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=255, blank=True, null=True)  # Field name made lowercase.
    fiig = models.CharField(db_column='FIIG', max_length=255, blank=True, null=True)  # Field name made lowercase.
    crit = models.CharField(db_column='CRIT', max_length=255, blank=True, null=True)  # Field name made lowercase.
    tiic = models.CharField(db_column='TIIC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    rpdmrc = models.CharField(db_column='RPDMRC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    adp = models.CharField(db_column='ADP', max_length=255, blank=True, null=True)  # Field name made lowercase.
    demil = models.CharField(db_column='DEMIL', max_length=255, blank=True, null=True)  # Field name made lowercase.
    hmic = models.CharField(db_column='HMIC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    esdemi = models.CharField(db_column='ESDEMI', max_length=255, blank=True, null=True)  # Field name made lowercase.
    pmi = models.CharField(db_column='PMI', max_length=255, blank=True, null=True)  # Field name made lowercase.
    supplychain = models.CharField(db_column='SupplyChain', max_length=255, blank=True, null=True)  # Field name made lowercase.
    ui = models.CharField(db_column='UI', max_length=255, blank=True, null=True)  # Field name made lowercase.
    total = models.CharField(db_column='Total', max_length=255, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_BID_PARTSBASE_DLA_TBL'


class StatzBidPartsbaseGenTbl(models.Model):
    genid = models.CharField(db_column='GenID', primary_key=True, max_length=36)  # Field name made lowercase.
    request = models.CharField(db_column='Request', max_length=255)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    part = models.CharField(db_column='Part', max_length=255, blank=True, null=True)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=255, blank=True, null=True)  # Field name made lowercase.
    schedule_b_code = models.CharField(db_column='Schedule_B_Code', max_length=255, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_BID_PARTSBASE_GEN_TBL'


class StatzBidPartsbaseMcrlTbl(models.Model):
    genid = models.CharField(db_column='GenID', primary_key=True, max_length=36)  # Field name made lowercase.
    request = models.CharField(db_column='Request', max_length=255, blank=True, null=True)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    part = models.CharField(db_column='Part', max_length=255, blank=True, null=True)  # Field name made lowercase.
    rncc = models.CharField(db_column='RNCC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    rnvc = models.CharField(db_column='RNVC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    rnfc = models.CharField(db_column='RNFC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    sadc = models.CharField(db_column='SADC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    dac = models.CharField(db_column='DAC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    vendor = models.CharField(db_column='VENDOR', max_length=255, blank=True, null=True)  # Field name made lowercase.
    comp_name = models.CharField(db_column='COMP_NAME', max_length=255, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_BID_PARTSBASE_MCRL_TBL'


class StatzBidPartsbaseProcTbl(models.Model):
    genid = models.CharField(db_column='GenID', primary_key=True, max_length=36)  # Field name made lowercase.
    request = models.CharField(db_column='Request', max_length=255, blank=True, null=True)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    awarddate = models.DateTimeField(db_column='AWARDDATE', blank=True, null=True)  # Field name made lowercase.
    contractno = models.CharField(db_column='CONTRACTNO', max_length=255, blank=True, null=True)  # Field name made lowercase.
    sos = models.CharField(db_column='SOS', max_length=255, blank=True, null=True)  # Field name made lowercase.
    unitprice = models.DecimalField(db_column='UNITPRICE', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    unitofmeasure = models.CharField(db_column='UNITOFMEASURE', max_length=255, blank=True, null=True)  # Field name made lowercase.
    quantity = models.IntegerField(db_column='QUANTITY', blank=True, null=True)  # Field name made lowercase.
    cage = models.CharField(db_column='CAGE', max_length=255, blank=True, null=True)  # Field name made lowercase.
    vendor = models.CharField(db_column='VENDOR', max_length=255, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_BID_PARTSBASE_PROC_TBL'


class StatzBidPartsbaseRequestTbl(models.Model):
    genid = models.CharField(db_column='GenID', max_length=36)  # Field name made lowercase.
    importid = models.AutoField(db_column='ImportID')  # Field name made lowercase.
    request = models.CharField(db_column='Request', primary_key=True, max_length=255)  # Field name made lowercase.
    dateadded = models.DateTimeField(db_column='DateAdded', blank=True, null=True)  # Field name made lowercase.
    expire = models.DateTimeField(db_column='Expire', blank=True, null=True)  # Field name made lowercase.
    pass_field = models.BooleanField(db_column='Pass')  # Field name made lowercase. Field renamed because it was a Python reserved word.
    queue = models.BooleanField(db_column='Queue')  # Field name made lowercase.
    expired = models.BooleanField(db_column='Expired')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_BID_PARTSBASE_REQUEST_TBL'


class StatzBidPartsbaseSolTbl(models.Model):
    genid = models.CharField(db_column='GenID', primary_key=True, max_length=36)  # Field name made lowercase.
    request = models.CharField(db_column='Request', max_length=255, blank=True, null=True)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationnumber = models.CharField(db_column='SolicitationNumber', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationtypeind = models.CharField(db_column='SolicitationTypeInd', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationsource = models.CharField(db_column='SolicitationSource', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationurl = models.CharField(db_column='SolicitationURL', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationtechdocsurl = models.CharField(db_column='SolicitationTechDocsURL', max_length=255, blank=True, null=True)  # Field name made lowercase.
    submitbid = models.CharField(db_column='SubmitBid', max_length=255, blank=True, null=True)  # Field name made lowercase.
    status = models.CharField(db_column='Status', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationcontactname = models.CharField(db_column='SolicitationContactName', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationcontactphone = models.CharField(db_column='SolicitationContactPhone', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationcontactemail = models.CharField(db_column='SolicitationContactEmail', max_length=255, blank=True, null=True)  # Field name made lowercase.
    solicitationissuedon = models.DateTimeField(db_column='SolicitationIssuedOn', blank=True, null=True)  # Field name made lowercase.
    solicitationexpireson = models.DateTimeField(db_column='SolicitationExpiresOn', blank=True, null=True)  # Field name made lowercase.
    linenumber = models.CharField(db_column='LineNumber', max_length=255, blank=True, null=True)  # Field name made lowercase.
    linenumbernsn = models.CharField(db_column='LineNumberNSN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    linenumberfsc = models.CharField(db_column='LineNumberFSC', max_length=255, blank=True, null=True)  # Field name made lowercase.
    linenumberniin = models.CharField(db_column='LineNumberNIIN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    linenumberqty = models.IntegerField(db_column='LineNumberQty', blank=True, null=True)  # Field name made lowercase.
    linenumberunitofissue = models.CharField(db_column='LineNumberUnitOfIssue', max_length=255, blank=True, null=True)  # Field name made lowercase.
    linenumberdescription = models.CharField(db_column='LineNumberDescription', max_length=255, blank=True, null=True)  # Field name made lowercase.
    firstarticleindicator = models.BooleanField(db_column='FirstArticleIndicator', blank=True, null=True)  # Field name made lowercase.
    hubzoneindicator = models.BooleanField(db_column='HubZoneIndicator', blank=True, null=True)  # Field name made lowercase.
    veteranownedindicator = models.BooleanField(db_column='VeteranOwnedIndicator', blank=True, null=True)  # Field name made lowercase.
    smallbusinessindicator = models.BooleanField(db_column='SmallBusinessIndicator', blank=True, null=True)  # Field name made lowercase.
    fob = models.CharField(db_column='FOB', max_length=255, blank=True, null=True)  # Field name made lowercase.
    higherquality = models.BooleanField(db_column='HigherQuality', blank=True, null=True)  # Field name made lowercase.
    solicitationinspectionlocation = models.CharField(db_column='SolicitationInspectionLocation', max_length=255, blank=True, null=True)  # Field name made lowercase.
    daystodeliveryfromaward = models.IntegerField(db_column='DaysToDeliveryFromAward', blank=True, null=True)  # Field name made lowercase.
    purchaserequestnumber = models.CharField(db_column='PurchaseRequestNumber', max_length=255, blank=True, null=True)  # Field name made lowercase.
    estimatedvalue = models.DecimalField(db_column='EstimatedValue', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    shippingaddress = models.TextField(db_column='ShippingAddress', blank=True, null=True)  # Field name made lowercase.
    pid = models.TextField(db_column='Pid', blank=True, null=True)  # Field name made lowercase.
    addedon = models.DateTimeField(db_column='AddedOn', blank=True, null=True)  # Field name made lowercase.
    reviewed = models.BooleanField(db_column='Reviewed', blank=True, null=True)  # Field name made lowercase.
    reviewedon = models.DateTimeField(db_column='ReviewedOn', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_BID_PARTSBASE_SOL_TBL'


class StatzBidPartsbaseVendorsTbl(models.Model):
    genid = models.CharField(db_column='GenID', primary_key=True, max_length=36)  # Field name made lowercase.
    request = models.CharField(db_column='Request', max_length=255, blank=True, null=True)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=255, blank=True, null=True)  # Field name made lowercase.
    cage = models.CharField(db_column='CAGE', max_length=255, blank=True, null=True)  # Field name made lowercase.
    vendor = models.CharField(db_column='Vendor', max_length=255, blank=True, null=True)  # Field name made lowercase.
    assoc = models.CharField(db_column='Assoc', max_length=255, blank=True, null=True)  # Field name made lowercase.
    address1 = models.CharField(db_column='Address1', max_length=255, blank=True, null=True)  # Field name made lowercase.
    address2 = models.CharField(db_column='Address2', max_length=255, blank=True, null=True)  # Field name made lowercase.
    pobox = models.CharField(db_column='POBox', max_length=255, blank=True, null=True)  # Field name made lowercase.
    city = models.CharField(db_column='City', max_length=255, blank=True, null=True)  # Field name made lowercase.
    state = models.CharField(db_column='State', max_length=255, blank=True, null=True)  # Field name made lowercase.
    zip = models.CharField(db_column='Zip', max_length=255, blank=True, null=True)  # Field name made lowercase.
    country = models.CharField(db_column='Country', max_length=255, blank=True, null=True)  # Field name made lowercase.
    telephone = models.CharField(db_column='Telephone', max_length=255, blank=True, null=True)  # Field name made lowercase.
    fax = models.CharField(db_column='Fax', max_length=255, blank=True, null=True)  # Field name made lowercase.
    cagetypecd = models.CharField(db_column='CAGETYPECD', max_length=255, blank=True, null=True)  # Field name made lowercase.
    cao = models.CharField(db_column='CAO', max_length=255, blank=True, null=True)  # Field name made lowercase.
    affiliationtype = models.CharField(db_column='AffiliationType', max_length=255, blank=True, null=True)  # Field name made lowercase.
    compsize = models.CharField(db_column='CompSize', max_length=255, blank=True, null=True)  # Field name made lowercase.
    businesstype = models.CharField(db_column='BusinessType', max_length=255, blank=True, null=True)  # Field name made lowercase.
    womanowned = models.CharField(db_column='WomanOwned', max_length=255, blank=True, null=True)  # Field name made lowercase.
    historicaluse = models.CharField(db_column='HISTORICALUSE', max_length=255, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_BID_PARTSBASE_VENDORS_TBL'


class StatzCashFlowTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    tabnum = models.CharField(db_column='TabNum', max_length=10)  # Field name made lowercase.
    ponum = models.CharField(db_column='PONum', max_length=10)  # Field name made lowercase.
    supplierid = models.IntegerField(db_column='SupplierID')  # Field name made lowercase.
    cf_amount = models.DecimalField(db_column='CF_Amount', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    cf_paid = models.BooleanField(db_column='CF_Paid')  # Field name made lowercase.
    cf_companyid = models.ForeignKey('StatzCfCompanyTbl', models.DO_NOTHING, db_column='CF_CompanyID', blank=True, null=True)  # Field name made lowercase.
    check_info = models.CharField(db_column='Check_Info', max_length=20, blank=True, null=True)  # Field name made lowercase.
    date_mailed = models.DateTimeField(db_column='Date_Mailed', blank=True, null=True)  # Field name made lowercase.
    est_shipdate = models.DateTimeField(db_column='Est_ShipDate', blank=True, null=True)  # Field name made lowercase.
    dfas_inv = models.CharField(db_column='DFAS_Inv', max_length=20, blank=True, null=True)  # Field name made lowercase.
    cf_statusid = models.ForeignKey('StatzCfStatusTbl', models.DO_NOTHING, db_column='CF_StatusID', blank=True, null=True)  # Field name made lowercase.
    cf_notes = models.CharField(db_column='CF_Notes', max_length=8000, blank=True, null=True)  # Field name made lowercase.
    cf_terms = models.CharField(db_column='CF_Terms', max_length=3, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_CASH_FLOW_TBL'


class StatzCfCompanyTbl(models.Model):
    id = models.OneToOneField('self', models.DO_NOTHING, db_column='ID', primary_key=True)  # Field name made lowercase.
    company = models.CharField(db_column='Company', max_length=5)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_CF_COMPANY_TBL'


class StatzCfStatusTbl(models.Model):
    id = models.IntegerField(db_column='ID', primary_key=True)  # Field name made lowercase.
    status = models.CharField(db_column='Status', max_length=50)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_CF_STATUS_TBL'


class StatzContractsDocsTbl(models.Model):
    contractdocid = models.AutoField(db_column='ContractDocID', primary_key=True)  # Field name made lowercase.
    contractid = models.IntegerField(db_column='ContractID', blank=True, null=True)  # Field name made lowercase.
    db = models.CharField(db_column='DB', max_length=25, blank=True, null=True)  # Field name made lowercase.
    docid = models.IntegerField(db_column='DocID', blank=True, null=True)  # Field name made lowercase.
    originalpath = models.TextField(db_column='OriginalPath', blank=True, null=True)  # Field name made lowercase.
    uploadeddate = models.DateTimeField(db_column='UploadedDate', blank=True, null=True)  # Field name made lowercase.
    uploadedby = models.CharField(db_column='UploadedBy', max_length=25, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_CONTRACTS_DOCS_TBL'


class StatzContractsTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    contractopen = models.BooleanField(db_column='ContractOpen')  # Field name made lowercase.
    contractcancelled = models.BooleanField(db_column='ContractCancelled')  # Field name made lowercase.
    tabnum = models.CharField(db_column='TabNum', max_length=10, blank=True, null=True)  # Field name made lowercase.
    ponumber = models.CharField(db_column='PONumber', max_length=10, blank=True, null=True)  # Field name made lowercase.
    contractnum = models.CharField(db_column='ContractNum', max_length=25, blank=True, null=True)  # Field name made lowercase.
    buyer_id = models.SmallIntegerField(db_column='Buyer_ID', blank=True, null=True)  # Field name made lowercase.
    type_id = models.IntegerField(db_column='Type_ID', blank=True, null=True)  # Field name made lowercase.
    award_date = models.DateTimeField(db_column='Award Date', blank=True, null=True)  # Field name made lowercase. Field renamed to remove unsuitable characters.
    contractduedate = models.DateTimeField(db_column='ContractDueDate', blank=True, null=True)  # Field name made lowercase.
    lateshipcdd = models.BooleanField(db_column='LateShipCDD')  # Field name made lowercase.
    datecancelled = models.DateTimeField(db_column='DateCancelled', blank=True, null=True)  # Field name made lowercase.
    reasoncancelled = models.IntegerField(db_column='ReasonCancelled', blank=True, null=True)  # Field name made lowercase.
    dateclosed = models.DateTimeField(db_column='DateClosed', blank=True, null=True)  # Field name made lowercase.
    salesclass = models.IntegerField(db_column='SalesClass', blank=True, null=True)  # Field name made lowercase.
    surveydate = models.DateField(db_column='SurveyDate', blank=True, null=True)  # Field name made lowercase.
    surveytype = models.CharField(db_column='SurveyType', max_length=10, blank=True, null=True)  # Field name made lowercase.
    assigneduser = models.CharField(db_column='AssignedUser', max_length=20, blank=True, null=True)  # Field name made lowercase.
    assigneddate = models.DateTimeField(db_column='AssignedDate', blank=True, null=True)  # Field name made lowercase.
    nist = models.BooleanField(db_column='NIST', blank=True, null=True)  # Field name made lowercase.
    url = models.CharField(db_column='URL', max_length=200, blank=True, null=True)  # Field name made lowercase.
    url_review = models.BooleanField(db_column='URL_Review', blank=True, null=True)  # Field name made lowercase.
    url_found = models.BooleanField(db_column='URL_Found', blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.
    modifiedby = models.CharField(db_column='ModifiedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    modifiedon = models.DateTimeField(db_column='ModifiedOn', blank=True, null=True)  # Field name made lowercase.
    reviewed = models.BooleanField(db_column='Reviewed')  # Field name made lowercase.
    reviewedby = models.CharField(db_column='ReviewedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    reviewedon = models.DateTimeField(db_column='ReviewedOn', blank=True, null=True)  # Field name made lowercase.
    sysstarttime = models.DateTimeField(db_column='SysStartTime')  # Field name made lowercase.
    sysendtime = models.DateTimeField(db_column='SysEndTime')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_CONTRACTS_TBL'


class StatzContractGovActionsTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    contractid = models.IntegerField(db_column='ContractID')  # Field name made lowercase.
    action = models.CharField(db_column='Action', max_length=3, blank=True, null=True)  # Field name made lowercase.
    action_number = models.CharField(db_column='Action_Number', max_length=30, blank=True, null=True)  # Field name made lowercase.
    request_type = models.CharField(db_column='Request_Type', max_length=15, blank=True, null=True)  # Field name made lowercase.
    date_submitted = models.DateTimeField(db_column='Date_Submitted', blank=True, null=True)  # Field name made lowercase.
    date_closed = models.DateTimeField(db_column='Date_Closed', blank=True, null=True)  # Field name made lowercase.
    initiatedby = models.CharField(db_column='InitiatedBy', max_length=10, blank=True, null=True)  # Field name made lowercase.
    rownumber = models.TextField(db_column='RowNumber')  # Field name made lowercase. This field type is a guess.

    class Meta:
        managed = False
        db_table = 'STATZ_CONTRACT_GOV_ACTIONS_TBL'


class StatzContractLogFieldsTbl(models.Model):
    subid = models.OneToOneField('StatzSubContractsTbl', models.DO_NOTHING, db_column='SubID', primary_key=True)  # Field name made lowercase.
    contractstatus = models.CharField(db_column='ContractStatus', max_length=8000, blank=True, null=True)  # Field name made lowercase.
    contractnotes = models.CharField(db_column='ContractNotes', max_length=8000, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_CONTRACT_LOG_FIELDS_TBL'


class StatzConvLogTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    vendor_id = models.IntegerField(db_column='Vendor_ID', blank=True, null=True)  # Field name made lowercase.
    contract_id = models.IntegerField(db_column='Contract_ID', blank=True, null=True)  # Field name made lowercase.
    vendoremp = models.CharField(db_column='VendorEmp', max_length=100, blank=True, null=True)  # Field name made lowercase.
    convdate = models.DateTimeField(db_column='ConvDate', blank=True, null=True)  # Field name made lowercase.
    username = models.CharField(db_column='UserName', max_length=20, blank=True, null=True)  # Field name made lowercase.
    method = models.CharField(db_column='Method', max_length=15, blank=True, null=True)  # Field name made lowercase.
    details = models.TextField(db_column='Details', blank=True, null=True)  # Field name made lowercase.
    rating = models.IntegerField(db_column='Rating', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_CONV_LOG_TBL'


class StatzCustLinksTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    username_id = models.IntegerField(db_column='UserName_ID', blank=True, null=True)  # Field name made lowercase.
    type = models.CharField(db_column='Type', max_length=255, blank=True, null=True)  # Field name made lowercase.
    linktext = models.CharField(db_column='LinkText', max_length=255, blank=True, null=True)  # Field name made lowercase.
    address = models.CharField(db_column='Address', max_length=255, blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=50, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.
    modifiedby = models.CharField(db_column='ModifiedBy', max_length=50, blank=True, null=True)  # Field name made lowercase.
    modifiedon = models.DateTimeField(db_column='ModifiedOn', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_CUST_LINKS_TBL'


class StatzDbVarsTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    type = models.CharField(db_column='Type', max_length=255, blank=True, null=True)  # Field name made lowercase.
    code = models.CharField(db_column='Code', max_length=255, blank=True, null=True)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=255, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_DB_VARS_TBL'


class StatzEmplTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    firstname = models.CharField(db_column='FirstName', max_length=50, blank=True, null=True)  # Field name made lowercase.
    lastname = models.CharField(db_column='LastName', max_length=50, blank=True, null=True)  # Field name made lowercase.
    username = models.CharField(db_column='UserName', max_length=20, blank=True, null=True)  # Field name made lowercase.
    password = models.CharField(db_column='Password', max_length=255, blank=True, null=True)  # Field name made lowercase.
    type = models.CharField(db_column='Type', max_length=10, blank=True, null=True)  # Field name made lowercase.
    permissionlevel = models.SmallIntegerField(db_column='PermissionLevel')  # Field name made lowercase.
    email = models.CharField(db_column='Email', max_length=50, blank=True, null=True)  # Field name made lowercase.
    positiontitle = models.CharField(db_column='PositionTitle', max_length=50, blank=True, null=True)  # Field name made lowercase.
    phonenum = models.CharField(db_column='PhoneNum', max_length=15, blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.
    modifiedby = models.CharField(db_column='ModifiedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    modifiedon = models.DateTimeField(db_column='ModifiedOn', blank=True, null=True)  # Field name made lowercase.
    currloggedin = models.BooleanField(db_column='CurrLoggedIn')  # Field name made lowercase.
    lastlogin = models.DateTimeField(db_column='LastLogIn', blank=True, null=True)  # Field name made lowercase.
    lastlogout = models.DateTimeField(db_column='LastLogout', blank=True, null=True)  # Field name made lowercase.
    logincomputer = models.CharField(db_column='LogInComputer', max_length=20, blank=True, null=True)  # Field name made lowercase.
    active = models.BooleanField(db_column='Active')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_EMPL_TBL'


class StatzErrLogTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    errdate = models.DateTimeField(db_column='ErrDate', blank=True, null=True)  # Field name made lowercase.
    compname = models.CharField(db_column='CompName', max_length=20, blank=True, null=True)  # Field name made lowercase.
    usrname = models.CharField(db_column='UsrName', max_length=20, blank=True, null=True)  # Field name made lowercase.
    errnumber = models.BigIntegerField(db_column='ErrNumber', blank=True, null=True)  # Field name made lowercase.
    errdesc = models.TextField(db_column='ErrDesc', blank=True, null=True)  # Field name made lowercase.
    errmodule = models.CharField(db_column='ErrModule', max_length=255, blank=True, null=True)  # Field name made lowercase.
    userdesc = models.CharField(db_column='UserDesc', max_length=8000, blank=True, null=True)  # Field name made lowercase.
    userskips = models.IntegerField(db_column='UserSkips', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_ERR_LOG_TBL'


class StatzExpeditesTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    subid = models.IntegerField(db_column='SubID', unique=True)  # Field name made lowercase.
    initiated = models.BooleanField(db_column='Initiated')  # Field name made lowercase.
    initiateddate = models.DateTimeField(db_column='InitiatedDate', blank=True, null=True)  # Field name made lowercase.
    initiatedby = models.CharField(db_column='InitiatedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    successful = models.BooleanField(db_column='Successful')  # Field name made lowercase.
    successfuldate = models.DateTimeField(db_column='SuccessfulDate', blank=True, null=True)  # Field name made lowercase.
    successfulby = models.CharField(db_column='SuccessfulBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    used = models.BooleanField(db_column='Used')  # Field name made lowercase.
    useddate = models.DateTimeField(db_column='UsedDate', blank=True, null=True)  # Field name made lowercase.
    usedby = models.CharField(db_column='UsedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_EXPEDITES_TBL'


class StatzFolderTrackingTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    contractid = models.IntegerField(db_column='ContractID', blank=True, null=True)  # Field name made lowercase.
    partial = models.CharField(db_column='Partial', max_length=20, blank=True, null=True)  # Field name made lowercase.
    stack = models.CharField(db_column='Stack', max_length=20, blank=True, null=True)  # Field name made lowercase.
    rts_email = models.BooleanField(db_column='RTS_Email')  # Field name made lowercase.
    qb_inv = models.CharField(db_column='QB_INV', max_length=10, blank=True, null=True)  # Field name made lowercase.
    wawf = models.BooleanField(db_column='WAWF')  # Field name made lowercase.
    wawf_qar = models.BooleanField(db_column='WAWF_QAR')  # Field name made lowercase.
    vsm_scn = models.CharField(db_column='VSM_SCN', max_length=20, blank=True, null=True)  # Field name made lowercase.
    vsm_bol = models.BooleanField(db_column='VSM_BOL')  # Field name made lowercase.
    pos = models.BooleanField(db_column='POS')  # Field name made lowercase.
    pod = models.BooleanField(db_column='POD')  # Field name made lowercase.
    dfas_paid = models.BooleanField(db_column='DFAS_PAID')  # Field name made lowercase.
    dfas_date = models.DateTimeField(db_column='DFAS_Date', blank=True, null=True)  # Field name made lowercase.
    paid_supplier = models.BooleanField(db_column='Paid_Supplier')  # Field name made lowercase.
    paid_ppi = models.BooleanField(db_column='PAID PPI')  # Field name made lowercase. Field renamed to remove unsuitable characters.
    note = models.CharField(db_column='Note', max_length=500, blank=True, null=True)  # Field name made lowercase.
    trackingtype = models.CharField(db_column='TrackingType', max_length=20, blank=True, null=True)  # Field name made lowercase.
    trackingnum = models.CharField(db_column='TrackingNum', max_length=20, blank=True, null=True)  # Field name made lowercase.
    close = models.BooleanField(db_column='Close')  # Field name made lowercase.
    highlight = models.BooleanField(db_column='Highlight')  # Field name made lowercase.
    sort_data = models.CharField(db_column='Sort_Data', max_length=20, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_FOLDER_TRACKING_TBL'


class StatzIdiqContractsTbl(models.Model):
    idiq_id = models.IntegerField(db_column='IDIQ_ID')  # Field name made lowercase.
    contract_id = models.IntegerField(db_column='Contract_ID', primary_key=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_IDIQ_CONTRACTS_TBL'


class StatzIdiqContractDetails(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    idiq_id = models.IntegerField(db_column='IDIQ_ID', blank=True, null=True)  # Field name made lowercase.
    nsnid = models.IntegerField(db_column='NSNID', blank=True, null=True)  # Field name made lowercase.
    supplierid = models.IntegerField(db_column='SUPPLIERID', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_IDIQ_CONTRACT_DETAILS'


class StatzIdiqTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    type = models.IntegerField(db_column='Type', blank=True, null=True)  # Field name made lowercase.
    contractnum = models.CharField(db_column='ContractNum', max_length=16, blank=True, null=True)  # Field name made lowercase.
    tabnum = models.CharField(db_column='TabNum', max_length=255, blank=True, null=True)  # Field name made lowercase.
    buyerid = models.IntegerField(db_column='BuyerID', blank=True, null=True)  # Field name made lowercase.
    awarddate = models.DateTimeField(db_column='AwardDate', blank=True, null=True)  # Field name made lowercase.
    termlength = models.IntegerField(db_column='TermLength', blank=True, null=True)  # Field name made lowercase.
    optionlength = models.IntegerField(db_column='OptionLength', blank=True, null=True)  # Field name made lowercase.
    idiqclosed = models.BooleanField(db_column='IDIQClosed')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_IDIQ_TBL'


class StatzNotesTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    type = models.CharField(db_column='Type', max_length=5)  # Field name made lowercase.
    ref_id = models.IntegerField(db_column='Ref_ID')  # Field name made lowercase.
    note = models.TextField(db_column='Note', blank=True, null=True)  # Field name made lowercase. This field type is a guess.
    createdby = models.CharField(db_column='CreatedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.
    modifiedby = models.CharField(db_column='ModifiedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    modifiedon = models.DateTimeField(db_column='ModifiedOn', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_NOTES_TBL'


class StatzNsnPriceHistTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    nsn_id = models.IntegerField(db_column='NSN_ID', blank=True, null=True)  # Field name made lowercase.
    subcontract_id = models.IntegerField(db_column='SubContract_ID', blank=True, null=True)  # Field name made lowercase.
    priceperpart = models.DecimalField(db_column='PricePerPart', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    govpriceperpart = models.DecimalField(db_column='GovPricePerPart', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.
    modifiedby = models.CharField(db_column='ModifiedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    modifiedon = models.DateTimeField(db_column='ModifiedOn', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_NSN_PRICE_HIST_TBL'


class StatzPayHistTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    subcontract_id = models.IntegerField(db_column='SubContract_ID')  # Field name made lowercase.
    paymenttype = models.CharField(db_column='PaymentType', max_length=15)  # Field name made lowercase.
    paymentamount = models.DecimalField(db_column='PaymentAmount', max_digits=19, decimal_places=4)  # Field name made lowercase.
    paymentdate = models.DateTimeField(db_column='PaymentDate', blank=True, null=True)  # Field name made lowercase.
    paymentinfo = models.TextField(db_column='PaymentInfo', blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_PAY_HIST_TBL'


class StatzPermsLvlCodeTbl(models.Model):
    id = models.SmallIntegerField(db_column='ID', primary_key=True)  # Field name made lowercase.
    leveldescription = models.CharField(db_column='LevelDescription', max_length=50)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_PERMS_LVL_CODE_TBL'


class StatzPoTemplatesTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    temp_title = models.CharField(db_column='TEMP_Title', max_length=100)  # Field name made lowercase.
    temp_body = models.TextField(db_column='TEMP_Body', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_PO_TEMPLATES_TBL'


class StatzQueryTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    qry_name = models.CharField(db_column='Qry_Name', max_length=255, blank=True, null=True)  # Field name made lowercase.
    qry_sql = models.TextField(db_column='Qry_SQL', blank=True, null=True)  # Field name made lowercase.
    userlevel = models.IntegerField(db_column='UserLevel', blank=True, null=True)  # Field name made lowercase.
    display = models.BooleanField(db_column='Display', blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.
    modifiedby = models.CharField(db_column='ModifiedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    modifiedon = models.DateTimeField(db_column='ModifiedOn', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_QUERY_TBL'


class StatzRemindersTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    heading = models.CharField(db_column='Heading', max_length=50, blank=True, null=True)  # Field name made lowercase.
    details = models.TextField(db_column='Details', blank=True, null=True)  # Field name made lowercase. This field type is a guess.
    reminderdate = models.DateTimeField(db_column='ReminderDate', blank=True, null=True)  # Field name made lowercase.
    reminderuser = models.CharField(db_column='ReminderUser', max_length=20, blank=True, null=True)  # Field name made lowercase.
    completed = models.BooleanField(db_column='Completed')  # Field name made lowercase.
    datecompleted = models.DateTimeField(db_column='DateCompleted', blank=True, null=True)  # Field name made lowercase.
    completedby = models.CharField(db_column='CompletedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    notes_id = models.IntegerField(db_column='Notes_ID', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_REMINDERS_TBL'


class StatzSeqNbrTbl(models.Model):
    po = models.BigIntegerField(db_column='PO')  # Field name made lowercase.
    tab = models.BigIntegerField(db_column='TAB')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_SEQ_NBR_TBL'


class StatzShipmentTrackingTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    clnid = models.IntegerField(db_column='CLNID')  # Field name made lowercase.
    groupid = models.CharField(db_column='GroupID', max_length=14)  # Field name made lowercase.
    shipment = models.CharField(db_column='Shipment', max_length=10, blank=True, null=True, db_comment='x of x')  # Field name made lowercase.
    carrier = models.CharField(db_column='Carrier', max_length=50, blank=True, null=True)  # Field name made lowercase.
    trackingnumber = models.CharField(db_column='TrackingNumber', max_length=50, blank=True, null=True, db_comment='alpha numeric number')  # Field name made lowercase.
    dateshipped = models.DateTimeField(db_column='DateShipped', blank=True, null=True)  # Field name made lowercase.
    datedelivered = models.DateTimeField(db_column='DateDelivered', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_SHIPMENT_TRACKING_TBL'


class StatzSubscribeTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    employee_id = models.IntegerField(db_column='Employee_ID', blank=True, null=True)  # Field name made lowercase.
    buyer_id = models.IntegerField(db_column='Buyer_ID', blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=50, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.
    modifiedby = models.CharField(db_column='ModifiedBy', max_length=50, blank=True, null=True)  # Field name made lowercase.
    modifiedon = models.DateTimeField(db_column='ModifiedOn', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_SUBSCRIBE_TBL'



class StatzSubContractsTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    contract_id = models.IntegerField(db_column='Contract_ID', blank=True, null=True)  # Field name made lowercase.
    type_id = models.IntegerField(db_column='Type_ID', blank=True, null=True)  # Field name made lowercase.
    open = models.CharField(db_column='Open', max_length=10, blank=True, null=True)  # Field name made lowercase.
    tabnum = models.CharField(db_column='TabNum', max_length=10, blank=True, null=True)  # Field name made lowercase.
    subponum = models.CharField(db_column='SubPONum', max_length=10, blank=True, null=True)  # Field name made lowercase.
    ponumber = models.CharField(db_column='PONumber', max_length=10, blank=True, null=True)  # Field name made lowercase.
    ponumext = models.CharField(db_column='PONumExt', max_length=5, blank=True, null=True)  # Field name made lowercase.
    sub_contract = models.CharField(db_column='Sub-Contract', max_length=20, blank=True, null=True)  # Field name made lowercase. Field renamed to remove unsuitable characters.
    vendor_id = models.IntegerField(db_column='Vendor_ID', blank=True, null=True)  # Field name made lowercase.
    nsn_id = models.IntegerField(db_column='NSN_ID', blank=True, null=True)  # Field name made lowercase.
    repeatnsn = models.BooleanField(db_column='RepeatNSN', blank=True, null=True)  # Field name made lowercase.
    ia = models.CharField(db_column='IA', max_length=5, blank=True, null=True)  # Field name made lowercase.
    fob = models.CharField(db_column='FOB', max_length=5, blank=True, null=True)  # Field name made lowercase.
    vendorduedate = models.DateTimeField(db_column='VendorDueDate', blank=True, null=True)  # Field name made lowercase.
    lateshipqdd = models.BooleanField(db_column='LateShipQDD')  # Field name made lowercase.
    orderqty = models.FloatField(db_column='OrderQty', blank=True, null=True)  # Field name made lowercase.
    ppp_cont = models.DecimalField(db_column='PPP_Cont', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    ppp_sup = models.DecimalField(db_column='PPP_Sup', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    shipdate = models.DateTimeField(db_column='ShipDate', blank=True, null=True)  # Field name made lowercase.
    lateship = models.BooleanField(db_column='LateShip')  # Field name made lowercase.
    shipqty = models.FloatField(db_column='ShipQty', blank=True, null=True)  # Field name made lowercase.
    subpodol = models.DecimalField(db_column='SubPODol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    subpaiddol = models.DecimalField(db_column='SubPaidDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    subpaiddate = models.DateTimeField(db_column='SubPaidDate', blank=True, null=True)  # Field name made lowercase.
    spt = models.BooleanField(db_column='SPT')  # Field name made lowercase.
    spt_type = models.CharField(db_column='SPT_Type', max_length=3, blank=True, null=True)  # Field name made lowercase.
    spt_paid = models.BooleanField(db_column='SPT_Paid')  # Field name made lowercase.
    contractdol = models.DecimalField(db_column='ContractDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    wawfpaymentdol = models.DecimalField(db_column='WAWFPaymentDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    datepayrecv = models.DateTimeField(db_column='DatePayRecv', blank=True, null=True)  # Field name made lowercase.
    plangrossdol = models.DecimalField(db_column='PlanGrossDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    actualpaidppidol = models.DecimalField(db_column='ActualPaidPPIDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    actualstatzdol = models.DecimalField(db_column='ActualSTATZDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    plansplit_per_ppibid = models.CharField(db_column='PlanSplit_per_PPIbid', max_length=50, blank=True, null=True)  # Field name made lowercase.
    ppisplitdol = models.DecimalField(db_column='PPISplitDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    statzsplitdol = models.DecimalField(db_column='STATZSplitDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    createdby = models.CharField(db_column='CreatedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    createdon = models.DateTimeField(db_column='CreatedOn', blank=True, null=True)  # Field name made lowercase.
    modifiedby = models.CharField(db_column='ModifiedBy', max_length=20, blank=True, null=True)  # Field name made lowercase.
    modifiedon = models.DateTimeField(db_column='ModifiedOn', blank=True, null=True)  # Field name made lowercase.
    sysstarttime = models.DateTimeField(db_column='SysStartTime')  # Field name made lowercase.
    sysendtime = models.DateTimeField(db_column='SysEndTime')  # Field name made lowercase.
    latesdd = models.BooleanField(db_column='LateSDD')  # Field name made lowercase.
    subduedate = models.DateTimeField(db_column='SubDueDate', blank=True, null=True)  # Field name made lowercase.
    pod = models.DateTimeField(db_column='POD', blank=True, null=True)  # Field name made lowercase.
    actualpaiddgcidol = models.DecimalField(db_column='ActualPaidDGCIDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    dgcisplitdol = models.DecimalField(db_column='DGCISplitDol', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    wawfinvoice = models.CharField(db_column='WAWFInvoice', max_length=25, blank=True, null=True)  # Field name made lowercase.
    cia_cos_interest_ppi = models.DecimalField(db_column='CIA_COS_Interest_PPI', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_SUB_CONTRACTS_TBL'


class StatzSurveyTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    contractid = models.ForeignKey(StatzContractsTbl, models.DO_NOTHING, db_column='ContractID')  # Field name made lowercase.
    surveytype = models.CharField(db_column='SurveyType', max_length=10)  # Field name made lowercase.
    supplierid = models.IntegerField(db_column='SupplierID')  # Field name made lowercase.
    score_po = models.IntegerField(db_column='Score_PO')  # Field name made lowercase.
    score_followup = models.IntegerField(db_column='Score_FollowUp')  # Field name made lowercase.
    score_emailresponse = models.IntegerField(db_column='Score_EmailResponse')  # Field name made lowercase.
    surveydate = models.DateTimeField(db_column='SurveyDate')  # Field name made lowercase.
    surveyuser = models.CharField(db_column='SurveyUser', max_length=20)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_SURVEY_TBL'


class StatzUserActivityTbl(models.Model):
    id = models.IntegerField()
    rowversion = models.TextField()  # This field type is a guess.
    username = models.CharField(max_length=50)
    computername = models.CharField(max_length=50)
    loginout = models.BooleanField(db_column='logInOut')  # Field name made lowercase.
    loginouttime = models.DateTimeField(db_column='LogInOutTime')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_USER_ACTIVITY_TBL'


class StatzWarehouseInventoryTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    nsn = models.CharField(db_column='NSN', max_length=50, blank=True, null=True)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=250, blank=True, null=True)  # Field name made lowercase.
    partnumber = models.CharField(db_column='PartNumber', max_length=50, blank=True, null=True)  # Field name made lowercase.
    manufacturer = models.CharField(db_column='Manufacturer', max_length=50, blank=True, null=True)  # Field name made lowercase.
    itemlocation = models.CharField(db_column='ItemLocation', max_length=50, blank=True, null=True)  # Field name made lowercase.
    quantity = models.IntegerField(db_column='Quantity', blank=True, null=True)  # Field name made lowercase.
    purchaseprice = models.DecimalField(db_column='PurchasePrice', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    totalcost = models.DecimalField(db_column='TotalCost', max_digits=19, decimal_places=4, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_WAREHOUSE_INVENTORY_TBL'


class StatzWiPageCodeTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    page = models.CharField(db_column='Page', max_length=100)  # Field name made lowercase.
    pagetitle = models.CharField(db_column='PageTitle', max_length=100, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_WI_PAGE_CODE_TBL'


class StatzWorkInstructionsTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    pageid = models.ForeignKey(StatzWiPageCodeTbl, models.DO_NOTHING, db_column='PageID')  # Field name made lowercase.
    wi_title = models.CharField(db_column='WI_Title', max_length=100)  # Field name made lowercase.
    wi_description = models.TextField(db_column='WI_Description', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'STATZ_WORK_INSTRUCTIONS_TBL'

