from django.db import models

# Create your models here.
class StatzContractsTbl(models.Model):
    id = models.AutoField(db_column='ID', primary_key=True)  # Field name made lowercase.
    contractopen = models.BooleanField(db_column='ContractOpen')  # Field name made lowercase.
    contractcancelled = models.BooleanField(db_column='ContractCancelled')  # Field name made lowercase.
    tabnum = models.CharField(db_column='TabNum', max_length=10, blank=True, null=True)  # Field name made lowercase.
    ponumber = models.CharField(db_column='PONumber', max_length=10, blank=True, null=True)  # Field name made lowercase.
    contractnum = models.CharField(db_column='ContractNum', max_length=25, blank=True, null=True)  # Field name made lowercase.
    buyer_id = models.SmallIntegerField(db_column='Buyer_ID', blank=True, null=True)  # Field name made lowercase.  Foreign Key to Buyer.ID
    type_id = models.IntegerField(db_column='Type_ID', blank=True, null=True)  # Field name made lowercase.  Foreign Key to ContractType.ID
    award_date = models.DateTimeField(db_column='Award Date', blank=True, null=True)  # Field name made lowercase. Field renamed to remove unsuitable characters.
    contractduedate = models.DateTimeField(db_column='ContractDueDate', blank=True, null=True)  # Field name made lowercase.
    lateshipcdd = models.BooleanField(db_column='LateShipCDD')  # Field name made lowercase.
    datecancelled = models.DateTimeField(db_column='DateCancelled', blank=True, null=True)  # Field name made lowercase.
    reasoncancelled = models.IntegerField(db_column='ReasonCancelled', blank=True, null=True)  # Field name made lowercase.
    dateclosed = models.DateTimeField(db_column='DateClosed', blank=True, null=True)  # Field name made lowercase.
    salesclass = models.IntegerField(db_column='SalesClass', blank=True, null=True)  # Field name made lowercase.  Foreign Key to SalesClass.ID
    surveydate = models.DateField(db_column='SurveyDate', blank=True, null=True)  # Field name made lowercase.
    surveytype = models.CharField(db_column='SurveyType', max_length=10, blank=True, null=True)  # Field name made lowercase.  Foreign Key to SurveyType.ID
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