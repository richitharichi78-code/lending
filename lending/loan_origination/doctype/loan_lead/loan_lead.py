# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanLead(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		address: DF.Link | None
		amended_from: DF.Link | None
		applicant_name: DF.Data
		company_name: DF.Data | None
		contact: DF.Link | None
		date_of_birth: DF.Date
		email: DF.Data | None
		email_otp: DF.Password | None
		email_verification_status: DF.Literal["Pending", "Initiated", "Verified"]
		employment_type: DF.Literal["Salaried", "Self-employed"]
		income: DF.Currency
		lead_source: DF.Data | None
		loan_amount: DF.Currency
		loan_product: DF.Link
		mobile_number: DF.Phone
		mobile_verification_status: DF.Literal["Pending", "Initiated", "Verified"]
		pan: DF.Data | None
		sms_otp: DF.Password | None
		status: DF.Data | None
	# end: auto-generated types

	pass
