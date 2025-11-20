# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import csv
import io
from types import MethodType

import frappe
from frappe import _
from frappe.core.doctype.data_import.exporter import Exporter
from frappe.model.document import Document
from frappe.utils import flt, getdate
from frappe.utils.background_jobs import enqueue, is_job_enqueued
from frappe.utils.csvutils import read_csv_content
from frappe.utils.scheduler import is_scheduler_inactive
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file


class LoanImportTool(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link
		create_missing_customers: DF.Check
		import_file: DF.Attach | None
		import_type: DF.Literal["Mid Tenure Loans", "Closed Loans"]
	# end: auto-generated types

	def validate(self):
		if not self.company:
			frappe.throw(_("Please select Company"))

	def get_field_mapping_from_meta(self):
		loan_meta = frappe.get_meta("Loan")
		return {
			field.label.strip(): field.fieldname
			for field in loan_meta.fields
			if field.label and field.fieldname
		}

	def get_additional_fields_mapping(self):
		return {
			"Loan Disbursement ID": "loan_disbursement_id",
			"Migration Date": "migration_date",
			"Principal Outstanding Amount": "principal_outstanding_amount",
			"Interest Outstanding Amount": "interest_outstanding_amount",
			"Penalty Outstanding Amount": "penalty_outstanding_amount",
			"Additional Outstanding Amount": "additional_outstanding_amount",
			"Charge Outstanding Amount": "charge_outstanding_amount",
		}

	def normalize_field_names(self, loan_data):
		loan_field_mapping = self.get_field_mapping_from_meta()
		additional_field_mapping = self.get_additional_fields_mapping()
		all_field_mapping = {**loan_field_mapping, **additional_field_mapping}
		normalized_data = []

		for loan_row in loan_data:
			normalized_row = {}
			invalid_fields = []

			for csv_field, value in loan_row.items():
				if not csv_field:
					continue

				csv_field_clean = csv_field.strip()
				if csv_field_clean in all_field_mapping:
					normalized_row[all_field_mapping[csv_field_clean]] = value
				else:
					invalid_fields.append(csv_field_clean)

			if invalid_fields:
				frappe.throw(_("Invalid field names found: {0}").format(", ".join(invalid_fields)))

			normalized_data.append(normalized_row)

		return normalized_data

	def process_import_file(self):
		import_file = frappe.get_doc("File", {"file_url": self.import_file})
		file_content = import_file.get_content()
		file_name = import_file.file_name

		if file_name.endswith(".csv"):
			loan_data = self.parse_csv_content(file_content)
		elif file_name.endswith((".xlsx", ".xls")):
			loan_data = self.parse_excel_content(import_file)
		else:
			frappe.throw(_("Unsupported file format. Please upload CSV or Excel file."))

		return self.normalize_field_names(loan_data)

	def parse_csv_content(self, content):
		rows = read_csv_content(content)
		if not rows or len(rows) < 2:
			frappe.throw(_("No data found in the file"))

		headers = [header.strip() for header in rows[0]]
		loan_data = []

		for row in rows[1:]:
			if not any(row):
				continue

			loan_row = {}
			for idx, header in enumerate(headers):
				if idx < len(row) and row[idx] is not None:
					value = row[idx]
					loan_row[header] = value.strip() if isinstance(value, str) else str(value)

			loan_data.append(loan_row)

		return loan_data

	def parse_excel_content(self, import_file):
		rows = read_xlsx_file_from_attached_file(fcontent=import_file.get_content())
		if not rows or len(rows) < 2:
			frappe.throw(_("No data found in the file"))

		headers = [str(header).strip() if header is not None else "" for header in rows[0]]
		loan_data = []

		for row in rows[1:]:
			if not any(row):
				continue

			loan_row = {}
			for idx, header in enumerate(headers):
				if idx < len(row) and row[idx] is not None:
					value = row[idx]
					loan_row[header] = str(value).strip() if isinstance(value, (str, int, float)) else str(value)

			loan_data.append(loan_row)

		return loan_data

	def validate_loan_data(self, loan_data):
		required_fields = [
			"loan_id",
			"loan_disbursement_id",
			"applicant_type",
			"applicant",
			"loan_product",
			"loan_amount",
			"posting_date",
			"company",
			"repayment_method",
			"repayment_frequency",
			"repayment_periods",
			"rate_of_interest",
			"penalty_charges_rate",
			"disbursement_date",
			"disbursed_amount",
			"repayment_start_date",
			"total_principal_paid",
			"total_interest_payable",
			"total_payment",
			"written_off_amount",
			"status",
		]

		if self.import_type == "Mid Tenure Loans":
			required_fields.extend(
				[
					"migration_date",
					"principal_outstanding_amount",
					"interest_outstanding_amount",
					"penalty_outstanding_amount",
					"additional_outstanding_amount",
					"charge_outstanding_amount",
				]
			)

		for i, loan in enumerate(loan_data):
			missing_fields = [field for field in required_fields if not loan.get(field)]
			if missing_fields:
				frappe.throw(
					_("Row {0}: Following fields are required: {1}").format(i + 1, ", ".join(missing_fields))
				)

			existing_loan_id = loan.get("loan_id")
			if existing_loan_id and frappe.db.exists("Loan", existing_loan_id):
				frappe.throw(_("Row {0}: Loan ID '{1}' already exists").format(i + 1, existing_loan_id))

			existing_disbursement_id = loan.get("loan_disbursement_id")
			if existing_disbursement_id and frappe.db.exists("Loan Disbursement", existing_disbursement_id):
				frappe.throw(
					_("Row {0}: Loan Disbursement ID '{1}' already exists").format(
						i + 1, existing_disbursement_id
					)
				)

			if not loan.get("company"):
				loan["company"] = self.company

			applicant_type = loan.get("applicant_type", "Customer")
			applicant = loan.get("applicant")

			if applicant and not frappe.db.exists(applicant_type, applicant):
				if self.create_missing_customers and applicant_type == "Customer":
					self.create_customer(applicant)
				else:
					frappe.throw(_("Row {0}: {1} {2} does not exist").format(i + 1, applicant_type, applicant))

			self.validate_numeric_fields(loan, i)
			self.validate_date_fields(loan, i)

	def validate_numeric_fields(self, loan, index):
		numeric_fields = [
			"loan_amount",
			"disbursed_amount",
			"rate_of_interest",
			"penalty_charges_rate",
			"total_principal_paid",
			"total_interest_payable",
			"total_payment",
			"written_off_amount",
			"principal_outstanding_amount",
			"interest_outstanding_amount",
			"penalty_outstanding_amount",
			"additional_outstanding_amount",
			"charge_outstanding_amount",
		]

		for field in numeric_fields:
			if loan.get(field):
				flt(loan[field])

	def validate_date_fields(self, loan, index):
		if self.import_type == "Mid Tenure Loans" and loan.get("migration_date"):
			getdate(loan["migration_date"])

		date_fields = ["posting_date", "repayment_start_date", "disbursement_date", "migration_date"]
		for field in date_fields:
			if loan.get(field):
				getdate(loan[field])

	def create_customer(self, customer_name):
		customer = frappe.new_doc("Customer")
		customer.customer_name = customer_name
		customer.customer_type = "Individual"
		customer.customer_group = (
			frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
		)
		customer.territory = (
			frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
		)
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)
		frappe.db.commit()
		frappe.msgprint(_("Created customer: {0}").format(customer_name))
		return customer.name

	def is_loc_loan(self, loan_product):
		return (
			frappe.db.get_value("Loan Product", loan_product, "repayment_schedule_type") == "Line of Credit"
		)

	def prepare_opening_gl_entry(self, loan_row, loan_name):
		loan_amount = flt(loan_row.get("loan_amount", 0))
		total_principal_paid = flt(loan_row.get("total_principal_paid", 0))
		outstanding_principal = loan_amount - total_principal_paid

		if outstanding_principal <= 0:
			return None

		loan_product_accounts = frappe.db.get_value(
			"Loan Product",
			loan_row.get("loan_product"),
			["loan_account", "payment_account"],
			as_dict=True,
		)

		loan_account = loan_product_accounts.get("loan_account")
		payment_account = loan_product_accounts.get("payment_account")

		if not loan_account or not payment_account:
			return None

		company = loan_row.get("company") or self.company
		cost_center = frappe.db.get_value("Company", company, "cost_center")
		posting_date = loan_row.get("migration_date")

		gl_entry_credit = {
			"doctype": "GL Entry",
			"posting_date": posting_date,
			"transaction_date": posting_date,
			"account": loan_account,
			"party_type": loan_row.get("applicant_type", "Customer"),
			"party": loan_row.get("applicant"),
			"against": payment_account,
			"credit": outstanding_principal,
			"credit_in_account_currency": outstanding_principal,
			"debit": 0,
			"debit_in_account_currency": 0,
			"voucher_type": "Loan",
			"voucher_no": loan_name,
			"company": company,
			"is_opening": "Yes",
			"cost_center": cost_center,
			"remarks": f"Opening entry for imported loan {loan_name}",
		}

		gl_entry_debit = {
			"doctype": "GL Entry",
			"posting_date": posting_date,
			"transaction_date": posting_date,
			"account": payment_account,
			"party_type": loan_row.get("applicant_type", "Customer"),
			"party": loan_row.get("applicant"),
			"against": loan_account,
			"debit": outstanding_principal,
			"debit_in_account_currency": outstanding_principal,
			"credit": 0,
			"credit_in_account_currency": 0,
			"voucher_type": "Loan",
			"voucher_no": loan_name,
			"company": company,
			"is_opening": "Yes",
			"cost_center": cost_center,
			"remarks": f"Opening entry for imported loan {loan_name}",
		}

		return [gl_entry_debit, gl_entry_credit]

	def prepare_loan_documents(self, loan_data):
		all_documents = []
		processed_loans = {}

		for index, loan_row in enumerate(loan_data):
			loan_id = loan_row.get("loan_id")
			is_loc = self.is_loc_loan(loan_row.get("loan_product"))

			if loan_id not in processed_loans:
				loan_doc = self.prepare_loan_doc(loan_row, is_loc)
				all_documents.append(loan_doc)
				processed_loans[loan_id] = loan_doc
			else:
				loan_doc = processed_loans[loan_id]

			disbursement_doc = self.prepare_loan_disbursement(loan_row, loan_doc, is_loc)
			disbursement_doc["_loan_row"] = loan_row
			all_documents.append(disbursement_doc)

			if self.import_type == "Mid Tenure Loans":
				loan_interest_accruals = self.prepare_loan_interest_accrual(
					loan_row, loan_doc, disbursement_doc
				)
				all_documents.extend(loan_interest_accruals)

				loan_demands = self.prepare_loan_demand(loan_row, loan_doc, disbursement_doc)
				all_documents.extend(loan_demands)

				gl_entries_placeholder = {
					"doctype": "GL Entry",
					"_is_gl_entry": True,
					"_loan_row": loan_row,
					"_loan_doc": loan_doc,
					"_disbursement_doc": disbursement_doc,
				}
				all_documents.append(gl_entries_placeholder)

		return all_documents

	def prepare_loan_interest_accrual(self, loan_row, loan_doc, disbursement_doc):
		documents = []
		migration_date = loan_row.get("migration_date")
		if not migration_date:
			return documents

		principal_outstanding = flt(loan_row.get("principal_outstanding_amount", 0))
		interest_outstanding = flt(loan_row.get("interest_outstanding_amount", 0))
		penalty_outstanding = flt(loan_row.get("penalty_outstanding_amount", 0))
		additional_outstanding = flt(loan_row.get("additional_outstanding_amount", 0))

		base_accrual = {
			"doctype": "Loan Interest Accrual",
			"company": loan_doc.get("company"),
			"loan": loan_doc.get("loan_id"),
			"loan_disbursement": disbursement_doc.get("loan_disbursement_id"),
			"applicant_type": loan_doc.get("applicant_type"),
			"applicant": loan_doc.get("applicant"),
			"loan_product": loan_row.get("loan_product"),
			"accrual_type": "Regular",
			"posting_date": migration_date,
			"accrual_date": migration_date,
			"start_date": loan_doc.get("disbursement_date"),
			"last_accrual_date": migration_date,
			"rate_of_interest": flt(loan_row.get("rate_of_interest", 0)),
			"is_term_loan": 1,
			"is_imported": 1,
		}

		if interest_outstanding > 0:
			normal_accrual = base_accrual.copy()
			normal_accrual.update(
				{
					"interest_type": "Normal Interest",
					"base_amount": principal_outstanding,
					"interest_amount": interest_outstanding,
					"accrued_interest": interest_outstanding,
					"total_pending_interest": interest_outstanding,
					"additional_interest_amount": 0,
					"penalty_amount": 0,
					"accrued_penalty": 0,
					"total_pending_penalty": 0,
				}
			)
			documents.append(normal_accrual)

		total_penal_interest = penalty_outstanding + additional_outstanding
		if total_penal_interest > 0:
			penal_accrual = base_accrual.copy()
			penal_accrual.update(
				{
					"interest_type": "Penal Interest",
					"additional_interest_amount": total_penal_interest,
					"base_amount": 0,
					"interest_amount": 0,
					"accrued_interest": 0,
					"total_pending_interest": 0,
				}
			)
			documents.append(penal_accrual)

		return documents

	def prepare_loan_demand(self, loan_row, loan_doc, disbursement_doc):
		documents = []
		migration_date = loan_row.get("migration_date")
		if not migration_date:
			return documents

		demand_components = [
			("EMI", "Principal", "principal_outstanding_amount"),
			("EMI", "Interest", "interest_outstanding_amount"),
			("Penalty", "Penalty", "penalty_outstanding_amount"),
			("Additional Interest", "Additional Interest", "additional_outstanding_amount"),
			("Charges", "Charges", "charge_outstanding_amount"),
		]

		for demand_type, demand_subtype, amount_field in demand_components:
			amount = flt(loan_row.get(amount_field, 0))
			if amount > 0:
				loan_demand = {
					"doctype": "Loan Demand",
					"company": loan_doc.get("company"),
					"loan": loan_doc.get("loan_id"),
					"loan_disbursement": disbursement_doc.get("loan_disbursement_id"),
					"applicant_type": loan_doc.get("applicant_type"),
					"applicant": loan_doc.get("applicant"),
					"loan_product": loan_row.get("loan_product"),
					"posting_date": migration_date,
					"demand_date": migration_date,
					"disbursement_date": loan_doc.get("disbursement_date"),
					"is_term_loan": 1,
					"demand_type": demand_type,
					"demand_subtype": demand_subtype,
					"demand_amount": amount,
					"outstanding_amount": amount,
					"paid_amount": 0,
					"waived_amount": 0,
					"status": "Unpaid",
					"is_imported": 1,
				}
				documents.append(loan_demand)

		return documents

	def prepare_loan_doc(self, loan_row, is_loc=False):
		cost_center = frappe.db.get_value(
			"Company", loan_row.get("company") or self.company, "cost_center"
		)
		if not cost_center:
			frappe.throw(
				_("Cost Center not defined for Company: {0}").format(loan_row.get("company") or self.company)
			)

		loan = {
			"doctype": "Loan",
			"loan_id": loan_row.get("loan_id"),
			"company": loan_row.get("company") or self.company,
			"loan_product": loan_row.get("loan_product"),
			"applicant_type": loan_row.get("applicant_type", "Customer"),
			"applicant": loan_row.get("applicant"),
			"loan_amount": flt(loan_row.get("loan_amount")),
			"rate_of_interest": flt(loan_row.get("rate_of_interest", 0)),
			"penalty_charges_rate": flt(loan_row.get("penalty_charges_rate", 0)),
			"posting_date": loan_row.get("posting_date"),
			"is_term_loan": 1,
			"status": loan_row.get("status", "Disbursed")
			if self.import_type == "Mid Tenure Loans"
			else "Closed",
			"total_principal_paid": flt(loan_row.get("total_principal_paid", 0)),
			"total_interest_payable": flt(loan_row.get("total_interest_payable", 0)),
			"total_payment": flt(loan_row.get("total_payment", 0)),
			"written_off_amount": flt(loan_row.get("written_off_amount", 0)),
			"cost_center": cost_center,
			"is_imported": 1,
		}

		if not is_loc:
			loan.update(
				{
					"repayment_method": loan_row.get("repayment_method"),
					"repayment_frequency": loan_row.get("repayment_frequency"),
					"repayment_periods": loan_row.get("repayment_periods"),
					"repayment_start_date": loan_row.get("repayment_start_date"),
					"disbursement_date": loan_row.get("disbursement_date"),
					"disbursed_amount": 0,
				}
			)
		else:
			loan.update(
				{
					"limit_applicable_start": loan_row.get("posting_date"),
					"maximum_limit_amount": flt(loan_row.get("loan_amount")),
					"disbursed_amount": 0,
				}
			)

		self.add_dynamic_fields(loan, loan_row)
		return loan

	def prepare_loan_disbursement(self, loan_row, loan_doc, is_loc=False):
		disbursement = {
			"doctype": "Loan Disbursement",
			"loan_disbursement_id": loan_row.get("loan_disbursement_id"),
			"company": loan_doc.get("company"),
			"against_loan": loan_doc.get("loan_id"),
			"disbursement_date": loan_row.get("disbursement_date"),
			"disbursed_amount": flt(loan_row.get("disbursed_amount")),
			"posting_date": loan_row.get("posting_date"),
			"is_imported": 1,
		}

		if is_loc:
			disbursement.update(
				{
					"repayment_method": loan_row.get("repayment_method"),
					"repayment_frequency": loan_row.get("repayment_frequency"),
					"repayment_periods": loan_row.get("repayment_periods"),
					"repayment_start_date": loan_row.get("repayment_start_date"),
				}
			)

		return disbursement

	def add_dynamic_fields(self, doc, row_data):
		loan_meta = frappe.get_meta("Loan")
		existing_fields = set(doc.keys())

		for field, value in row_data.items():
			if field and value is not None and field not in existing_fields:
				if loan_meta.has_field(field) or field.startswith("custom_"):
					if isinstance(value, str):
						value = value.strip()
						try:
							doc[field] = flt(value) if "." in value else int(value)
						except (ValueError, TypeError):
							doc[field] = value
					else:
						doc[field] = value

	@frappe.whitelist()
	def import_loans(self):
		self.validate()
		loan_data = self.process_import_file()
		self.validate_loan_data(loan_data)
		all_documents = self.prepare_loan_documents(loan_data)

		if len(all_documents) < 50:
			return start_loan_import(all_documents, self.import_type)
		else:
			run_now = frappe.in_test or frappe.conf.developer_mode
			if is_scheduler_inactive() and not run_now:
				frappe.throw(_("Scheduler is inactive. Cannot import data."), title=_("Scheduler Inactive"))

			job_id = f"loan_import::{self.name}"
			if not is_job_enqueued(job_id):
				enqueue(
					start_loan_import,
					queue="default",
					timeout=10000,
					event="loan_import",
					job_id=job_id,
					documents=all_documents,
					import_type=self.import_type,
					now=run_now,
				)


def start_loan_import(documents, import_type):
	errors = 0
	created_documents = []

	loan_documents = []
	disbursement_documents = []
	interest_accrual_documents = []
	loan_demand_documents = []
	gl_entry_documents = []

	for doc in documents:
		if doc.get("doctype") == "Loan":
			loan_documents.append(doc)
		elif doc.get("doctype") == "Loan Disbursement":
			disbursement_documents.append(doc)
		elif doc.get("doctype") == "Loan Interest Accrual":
			interest_accrual_documents.append(doc)
		elif doc.get("doctype") == "Loan Demand":
			loan_demand_documents.append(doc)
		elif doc.get("_is_gl_entry"):
			gl_entry_documents.append(doc)

	created_loans = {}
	created_disbursements = {}

	created_loans = create_loan_documents(loan_documents)
	created_disbursements = create_disbursement_documents(disbursement_documents, created_loans)

	if gl_entry_documents:
		create_gl_entries(gl_entry_documents, created_loans)

	if interest_accrual_documents:
		create_interest_accrual_documents(
			interest_accrual_documents, created_loans, created_disbursements
		)

	if loan_demand_documents:
		create_loan_demand_documents(loan_demand_documents, created_loans, created_disbursements)

	frappe.db.commit()

	if errors > 0:
		publish_final_status(len(documents), len(documents), "partial_success")
		frappe.msgprint(_("Completed with {0} errors.").format(errors), indicator="orange")
	else:
		publish_final_status(len(documents), len(documents), "success")
		frappe.msgprint(_("Loan import completed successfully!"), indicator="green")

	return created_documents


def create_loan_documents(loan_documents):
	created_loans = {}
	for idx, loan_dict in enumerate(loan_documents):
		publish(idx, len(loan_documents), "Loan")
		loan_id = loan_dict.get("loan_id")

		if loan_id in created_loans:
			continue

		loan = frappe.get_doc(loan_dict)
		loan.flags.ignore_mandatory = True
		loan.flags.ignore_validate = True
		loan.insert(ignore_permissions=True)
		loan.submit()

		created_loans[loan_id] = loan.name

	return created_loans


def create_disbursement_documents(disbursement_documents, created_loans):
	created_disbursements = {}
	for idx, disbursement_dict in enumerate(disbursement_documents):
		loan_id = disbursement_dict.get("against_loan")
		disbursement_id = disbursement_dict.get("loan_disbursement_id")

		if not loan_id or loan_id not in created_loans:
			frappe.throw(_("No matching loan found for disbursement {0}").format(disbursement_id))

		if disbursement_id in created_disbursements:
			continue

		disbursement_dict["against_loan"] = created_loans[loan_id]
		disbursement = frappe.get_doc(disbursement_dict)
		disbursement.flags.ignore_mandatory = True
		disbursement.flags.ignore_validate = True
		disbursement.insert(ignore_permissions=True)
		disbursement.make_gl_entries = MethodType(lambda self, *a, **kw: None, disbursement)
		disbursement.status = "Submitted"
		disbursement.submit()

		created_disbursements[disbursement_id] = disbursement.name

		loan_row = disbursement_dict.get("_loan_row", {})
		migration_date = loan_row.get("migration_date")

		update_demand_generated_for_repayment_schedule(
			created_loans[loan_id],
			disbursement.name,
			migration_date,
		)

	return created_disbursements


def create_gl_entries(gl_entry_documents, created_loans):
	for idx, gl_placeholder in enumerate(gl_entry_documents):
		loan_row = gl_placeholder.get("_loan_row")
		loan_doc = gl_placeholder.get("_loan_doc")

		loan_id = loan_doc.get("loan_id")

		if not loan_id or loan_id not in created_loans:
			frappe.throw(_("No matching loan found for GL entry for loan ID: {0}").format(loan_id))

		loan_name = created_loans[loan_id]

		loan_import_tool = frappe.new_doc("Loan Import Tool")
		gl_entries = loan_import_tool.prepare_opening_gl_entry(loan_row, loan_name)

		if gl_entries:
			for gl_entry_dict in gl_entries:
				gl_entry = frappe.get_doc(gl_entry_dict)
				gl_entry.flags.ignore_mandatory = True
				gl_entry.flags.ignore_validate = True
				gl_entry.insert(ignore_permissions=True)
				gl_entry.submit()


def create_interest_accrual_documents(
	interest_accrual_documents, created_loans, created_disbursements
):
	for idx, accrual_dict in enumerate(interest_accrual_documents):
		loan_id = accrual_dict.get("loan")
		disbursement_id = accrual_dict.get("loan_disbursement")

		if not loan_id or loan_id not in created_loans:
			frappe.throw(_("No matching loan found for interest accrual"))

		if not disbursement_id or disbursement_id not in created_disbursements:
			frappe.throw(_("No matching disbursement found for interest accrual"))

		accrual_dict["loan"] = created_loans[loan_id]
		accrual_dict["loan_disbursement"] = created_disbursements[disbursement_id]

		accrual = frappe.get_doc(accrual_dict)
		accrual.flags.ignore_mandatory = True
		accrual.flags.ignore_validate = True
		accrual.flags.ignore_gl_entries = True
		accrual.insert(ignore_permissions=True)
		accrual.make_gl_entries = MethodType(lambda self, *a, **kw: None, accrual)
		accrual.submit()


def create_loan_demand_documents(loan_demand_documents, created_loans, created_disbursements):
	for idx, demand_dict in enumerate(loan_demand_documents):
		loan_id = demand_dict.get("loan")
		disbursement_id = demand_dict.get("loan_disbursement")

		if not loan_id or loan_id not in created_loans:
			frappe.throw(_("No matching loan found for loan demand"))

		if not disbursement_id or disbursement_id not in created_disbursements:
			frappe.throw(_("No matching disbursement found for loan demand"))

		demand_dict["loan"] = created_loans[loan_id]
		demand_dict["loan_disbursement"] = created_disbursements[disbursement_id]

		demand = frappe.get_doc(demand_dict)
		demand.flags.ignore_mandatory = True
		demand.flags.ignore_validate = True
		demand.insert(ignore_permissions=True)
		demand.make_gl_entries = MethodType(lambda self, *a, **kw: None, demand)
		demand.submit()


def update_demand_generated_for_repayment_schedule(loan_name, disbursement_name, migration_date):
	if not migration_date:
		return

	frappe.db.sql(
		"""
		UPDATE `tabRepayment Schedule` rs
		INNER JOIN `tabLoan Repayment Schedule` lrs ON lrs.name = rs.parent
		SET rs.demand_generated = 1
		WHERE lrs.loan = %s
		AND lrs.loan_disbursement = %s
		AND lrs.docstatus = 1
		AND lrs.status = 'Active'
		AND rs.payment_date < %s
		""",
		(loan_name, disbursement_name, migration_date),
	)
	frappe.db.commit()


def publish(index, total, doctype):
	frappe.publish_realtime(
		"loan_import_progress",
		{
			"title": _("Loan Import In Progress"),
			"message": _("Creating {0} out of {1} {2}").format(index + 1, total, doctype),
			"count": index + 1,
			"total": total,
		},
		user=frappe.session.user,
	)


def publish_final_status(count, total, status):
	frappe.publish_realtime(
		"loan_import_progress",
		{
			"title": _("Loan Import Completed"),
			"message": _("Import completed"),
			"count": count,
			"total": total,
			"status": status,
		},
		user=frappe.session.user,
	)


@frappe.whitelist()
def loan_template_download(
	doctype,
	import_type=None,
	export_fields=None,
	export_records=None,
	export_filters=None,
	file_type="CSV",
):
	frappe.has_permission(doctype, "read", throw=True)

	export_fields = frappe.parse_json(export_fields)
	export_filters = frappe.parse_json(export_filters)
	export_data = export_records != "blank_template"

	static_fields = []
	if import_type == "Mid Tenure Loans":
		if doctype == "Loan":
			static_fields = [
				"Loan Disbursement ID",
				"Migration Date",
				"Principal Outstanding Amount",
				"Interest Outstanding Amount",
				"Penalty Outstanding Amount",
				"Additional Outstanding Amount",
				"Charge Outstanding Amount",
			]

	exporter = Exporter(
		doctype,
		export_fields=export_fields,
		export_data=export_data,
		export_filters=export_filters,
		file_type=file_type,
		export_page_length=5 if export_records == "5_records" else None,
	)

	csv_array = exporter.get_csv_array_for_export()

	if csv_array and csv_array[0]:
		csv_array[0].extend(static_fields)

	output = io.StringIO()
	writer = csv.writer(output)
	writer.writerows(csv_array)

	if doctype == "Loan":
		frappe.response.filename = "loan_import_template.csv"
	else:
		frappe.response.filename = "loan_repayment_import_template.csv"

	frappe.response.filecontent = output.getvalue().encode("utf-8")
	frappe.response.type = "download"
