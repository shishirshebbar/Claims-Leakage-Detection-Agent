"""Canonical schema: entities, fields, header synonyms and role requirements."""
import re

# field -> (weight, synonyms). Synonyms are matched against normalised headers.
ENTITIES = {
    "claims": {
        "claim_id": (3, ["claimid", "claimno", "claimnumber", "claimnum", "claimref", "claimreference", "claim", "clmid", "claimidentifier", "caseid"]),
        "policy_id": (2, ["policyid", "policyno", "policynumber", "policynum", "policyref", "policy"]),
        "claimant_id": (2, ["claimantid", "claimant", "claimantname", "beneid", "beneficiaryid", "customerid", "insuredid", "insured", "patientid", "patient", "memberid", "member", "policyholder", "holderid"]),
        "provider": (2, ["provider", "providerid", "hospital", "garage", "serviceprovider", "providername", "facility", "repairer", "repairshop", "workshop"]),
        "claim_type": (2, ["claimtype", "type", "claimcategory", "losstype", "causeofloss", "peril", "claimnature"]),
        "loss_date": (2, ["lossdate", "dateofloss", "incidentdate", "accidentdate", "dateofincident", "eventdate", "claimstartdt", "claimstartdate", "servicedate", "treatmentdate"]),
        "claim_date": (1, ["claimdate", "dateofclaim", "reporteddate", "submissiondate", "claimsubmitteddate", "intimationdate", "fnoldate", "claimenddt", "claimenddate"]),
        "admission_date": (1, ["admissiondate", "admissiondt", "admitdate", "dateofadmission"]),
        "discharge_date": (1, ["dischargedate", "dischargedt", "dateofdischarge"]),
        "claimed_amount": (3, ["claimedamount", "claimamount", "amountclaimed", "totalclaimed", "billedamount", "totalbill", "claimtotal", "requestedamount", "totalamount", "grossamount", "claimvalue"]),
        "proposed_settlement": (3, ["proposedsettlement", "settlementamount", "settlement", "proposedamount", "approvedamount", "payableamount", "amountpaid", "paidamount", "insclaimamtreimbursed", "reimbursed", "reimbursedamount", "settledamount", "payout", "proposedpayout", "netpayable"]),
        "status": (1, ["status", "claimstatus", "state"]),
        "invoice_no": (1, ["invoiceno", "invoicenumber", "invoiceid", "invoice", "billno", "billnumber", "invoiceref", "invno", "invnumber", "invref", "billref", "receiptno", "receiptnumber"]),
        "description": (1, ["claimdescription", "incidentdescription", "narrative", "remarks"]),
        "bank_account": (1, ["bankaccount", "accountnumber", "accountno", "iban", "payeeaccount", "beneficiaryaccount"]),
        "phone": (1, ["phone", "phonenumber", "mobile", "contactnumber", "telephone"]),
        "address": (1, ["address", "claimantaddress", "residentialaddress"]),
        "diagnosis": (1, ["diagnosis", "diagnosiscode", "icd", "clmadmitdiagnosiscode", "clmdiagnosiscode1", "procedurecode"]),
        "deductible_applied": (1, ["deductibleapplied", "deductiblepaid", "deductibleamtpaid", "deductiblededucted"]),
        "copay_applied": (1, ["copayapplied", "copaypaid", "copaydeducted"]),
        "currency": (1, ["currency", "currencycode", "ccy"]),
    },
    "policies": {
        "policy_id": (3, ["policyid", "policyno", "policynumber", "policynum", "policyref", "policy"]),
        "coverage_limit": (3, ["coveragelimit", "sumassured", "suminsured", "limit", "policylimit", "maxcoverage", "coverageamount", "overalllimit", "benefitlimit", "annuallimit", "maximumbenefit"]),
        "deductible": (3, ["deductible", "excess", "policydeductible", "deductibleamount"]),
        "copay_pct": (2, ["copaypct", "copay", "copayment", "copaypercent", "copaypercentage", "coinsurance"]),
        "start_date": (2, ["startdate", "policystart", "policystartdate", "inceptiondate", "effectivedate", "coveragestart", "policyeffectivedate", "commencementdate"]),
        "end_date": (2, ["enddate", "policyend", "policyenddate", "expirydate", "expirationdate", "coverageend", "expiry", "maturitydate"]),
        "room_limit_per_day": (2, ["roomlimitperday", "roomrentlimit", "roomlimit", "dailyroomlimit", "roomrent", "roomcap", "roomrentcap"]),
        "exclusions": (3, ["exclusions", "excludedservices", "excluded", "exclusionlist", "notcovered", "excludeditems"]),
        "sub_limits": (3, ["sublimits", "sublimit", "categorylimits", "benefitcaps", "caps"]),
        "waiting_days": (2, ["waitingdays", "waitingperiod", "waitingperioddays"]),
        "policy_type": (1, ["policytype", "plan", "plantype", "product", "producttype"]),
        "required_documents": (2, ["requireddocuments", "requireddocs", "mandatorydocuments"]),
    },
    "lines": {
        "claim_id": (3, ["claimid", "claimno", "claimnumber", "claimnum", "claimref", "claim", "clmid"]),
        "line_id": (1, ["lineid", "lineno", "linenumber", "itemid", "itemno", "sno", "serial"]),
        "invoice_no": (3, ["invoiceno", "invoicenumber", "invoiceid", "invoice", "billno", "billnumber", "invoiceref", "invno", "invnumber", "invref", "billref", "receiptno", "receiptnumber"]),
        "vendor": (2, ["vendor", "provider", "providerid", "supplier", "hospital", "garage", "billedby", "serviceprovider", "providername", "facility", "repairer"]),
        "invoice_date": (2, ["invoicedate", "billdate", "dateofinvoice", "billingdate"]),
        "service_date": (2, ["servicedate", "dateofservice", "treatmentdate", "itemdate", "chargedate"]),
        "description": (3, ["description", "itemdescription", "service", "servicedescription", "item", "particulars", "chargedescription", "lineitem", "details", "procedure", "narration", "itemname"]),
        "category": (2, ["category", "servicecategory", "chargetype", "itemcategory", "linetype", "expensetype", "headofcharge", "chargecategory"]),
        "quantity": (2, ["quantity", "qty", "units", "days", "noofunits", "nos"]),
        "unit_price": (2, ["unitprice", "rate", "priceperunit", "unitcost", "unitrate", "perdayrate"]),
        "amount": (3, ["amount", "lineamount", "linetotal", "charge", "billed", "netamount", "totalprice", "itemamount", "chargeamount", "price", "cost", "value"]),
        "invoice_total": (1, ["invoicetotal", "totalinvoiceamount", "billtotal", "invoiceamount", "grandtotal", "totalbillamount"]),
        "currency": (1, ["currency", "currencycode", "ccy"]),
    },
    "payments": {
        "payment_id": (3, ["paymentid", "paymentno", "txnid", "transactionid", "paymentref", "voucherno", "settlementid"]),
        "claim_id": (3, ["claimid", "claimno", "claimnumber", "claimnum", "claimref", "claim", "clmid"]),
        "invoice_no": (2, ["invoiceno", "invoicenumber", "invoiceid", "invoice", "billno", "billnumber", "invoiceref", "invno", "invnumber", "invref", "billref", "receiptno", "receiptnumber"]),
        "amount": (3, ["paymentamount", "amountpaid", "paidamount", "amount", "payout", "settledamount", "netpaid"]),
        "payment_date": (2, ["paymentdate", "paiddate", "dateofpayment", "settlementdate", "valuedate", "paydate"]),
        "method": (2, ["method", "paymentmethod", "settlementmethod", "mode", "paymentmode", "settlementmode", "channel", "paymenttype"]),
        "reference": (2, ["reference", "paymentreference", "utr", "chequeno", "referenceno", "refno", "transactionreference", "utrno"]),
        "currency": (1, ["currency", "currencycode", "ccy"]),
    },
    "documents": {
        "claim_id": (3, ["claimid", "claimno", "claimnumber", "claimnum", "claimref", "claim", "clmid"]),
        "doc_type": (3, ["doctype", "documenttype", "document", "doctypename", "attachmenttype", "type", "doccategory"]),
        "doc_name": (1, ["docname", "documentname", "filename", "file", "attachment"]),
    },
}


def role_ok(entity, mapped):
    """What must be present for a table to play a role."""
    m = set(mapped)
    if entity == "claims":
        return "claim_id" in m and bool(m & {"claimed_amount", "proposed_settlement", "claim_type", "provider", "loss_date", "claimant_id", "policy_id"})
    if entity == "policies":
        return "policy_id" in m and bool(m & {"coverage_limit", "deductible", "exclusions", "start_date", "end_date", "sub_limits", "copay_pct", "room_limit_per_day"})
    if entity == "lines":
        return "amount" in m and bool(m & {"claim_id", "invoice_no"}) and bool(m & {"description", "unit_price", "quantity", "category"})
    if entity == "payments":
        return "amount" in m and bool(m & {"claim_id", "invoice_no"}) and bool(m & {"payment_id", "reference", "method", "payment_date"})
    if entity == "documents":
        return {"claim_id", "doc_type"} <= m
    return False


def norm_header(h):
    return re.sub(r"[^a-z0-9]", "", str(h).lower())


ENTITY_LABELS = {
    "claims": "Claims",
    "policies": "Policy coverage",
    "lines": "Invoice lines",
    "payments": "Payments / settlement",
    "documents": "Supporting documents",
}
