# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import csv
import io
import traceback
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
		import_for: DF.Literal["Loan", "Loan Repayment"]
		import_type: DF.Literal["Mid Tenure Loans", "Closed Loans"]
	# end: auto-generated types

	def validate(self):
		if not self.company:
			frappe.throw(_("Please select Company"))

	def get_field_mapping_from_meta(self, import_for):
		if import_for == "Loan":
			loan_meta = frappe.get_meta("Loan")
		else:
			loan_meta = frappe.get_meta("Loan Repayment")

		return {
			field.label.strip(): field.fieldname
			for field in loan_meta.fields
			if field.label and field.fieldname
		}

	def get_additional_fields_mapping(self, import_for):
		if import_for == "Loan":
			return {
				"Loan Disbursement ID": "loan_disbursement_id",
				"Migration Date": "migration_date",
				"Principal Outstanding Amount": "principal_outstanding_amount",
				"Interest Outstanding Amount": "interest_outstanding_amount",
				"Penalty Outstanding Amount": "penalty_outstanding_amount",
				"Additional Outstanding Amount": "additional_outstanding_amount",
				"Charge Outstanding Amount": "charge_outstanding_amount",
			}
		return {}

	def normalize_field_names(self, import_for, loan_data):
		loan_field_mapping = self.get_field_mapping_from_meta(import_for)
		additional_field_mapping = self.get_additional_fields_mapping(import_for)

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

	def process_import_file(self, import_for):
		import_file = frappe.get_doc("File", {"file_url": self.import_file})
		file_content = import_file.get_content()
		file_name = import_file.file_name

		if file_name.endswith(".csv"):
			loan_data = self.parse_csv_content(file_content)
		elif file_name.endswith((".xlsx", ".xls")):
			loan_data = self.parse_excel_content(import_file)
		else:
			frappe.throw(_("Unsupported file format. Please upload CSV or Excel file."))

		return self.normalize_field_names(import_for, loan_data)

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

	def validate_import_data(self, import_data):
		"""Validate import data and return list of validation errors"""
		validation_results = []

		if self.import_for == "Loan":
			validation_results = self.validate_loan_data(import_data)
		else:
			validation_results = self.validate_loan_repayment_data(import_data)

		return validation_results

	def validate_loan_data(self, loan_data):
		"""Validate loan import data with option to skip duplicates"""
		errors = []
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
			row_errors = []
			row_number = i + 1

			missing_fields = [field for field in required_fields if not loan.get(field)]
			if missing_fields:
				row_errors.append(_("Following fields are required: {0}").format(", ".join(missing_fields)))

			existing_loan_id = loan.get("loan_id")
			if existing_loan_id and frappe.db.exists("Loan", existing_loan_id):
				row_errors.append(_("Loan ID '{0}' already exists").format(existing_loan_id))

			existing_disbursement_id = loan.get("loan_disbursement_id")
			if existing_disbursement_id and frappe.db.exists("Loan Disbursement", existing_disbursement_id):
				row_errors.append(
					_("Loan Disbursement ID '{0}' already exists").format(existing_disbursement_id)
				)

			if not loan.get("company"):
				loan["company"] = self.company

			applicant_type = loan.get("applicant_type", "Customer")
			applicant = loan.get("applicant")
			if applicant and not frappe.db.exists(applicant_type, applicant):
				if self.create_missing_customers and applicant_type == "Customer":
					try:
						self.create_customer(applicant)
					except Exception as e:
						row_errors.append(_("Failed to create customer: {0}").format(str(e)))
				else:
					row_errors.append(_("{0} {1} does not exist").format(applicant_type, applicant))

			numeric_errors = self.validate_numeric_fields(loan, i)
			if numeric_errors:
				row_errors.extend(numeric_errors)

			date_errors = self.validate_date_fields(loan, i)
			if date_errors:
				row_errors.extend(date_errors)

			for error in row_errors:
				errors.append({"row": row_number, "error": error})

		return errors

	def validate_numeric_fields(self, loan, index):
		errors = []
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
				try:
					flt(loan[field])
				except ValueError:
					errors.append(_("Invalid numeric value for field {0}").format(field))

		return errors

	def validate_date_fields(self, loan, index):
		errors = []
		if self.import_type == "Mid Tenure Loans" and loan.get("migration_date"):
			try:
				getdate(loan["migration_date"])
			except Exception:
				errors.append(_("Invalid date format for migration_date"))

		date_fields = ["posting_date", "repayment_start_date", "disbursement_date", "migration_date"]
		for field in date_fields:
			if loan.get(field):
				try:
					getdate(loan[field])
				except Exception:
					errors.append(_("Invalid date format for field {0}").format(field))

		return errors

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
		frappe.db.commit()  # nosemgrep
		frappe.msgprint(_("Created customer: {0}").format(customer_name))
		return customer.name

	def is_loc_loan(self, loan_product):
		return (
			frappe.db.get_value("Loan Product", loan_product, "repayment_schedule_type") == "Line of Credit"
		)

	def prepare_opening_gl_entry(self, loan_row, loan_name):
		if self.import_type == "Closed Loans":
			return None

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

	def prepare_import_documents(self, import_data):
		if self.import_for == "Loan":
			return self.prepare_loan_documents(import_data)
		else:
			return self.prepare_loan_repayment_documents(import_data)

	def prepare_loan_documents(self, loan_data):
		if self.import_type == "Closed Loans":
			return self.prepare_closed_loan_documents(loan_data)

		all_documents = []
		processed_loans = {}

		for index, loan_row in enumerate(loan_data):
			loan_id = loan_row.get("loan_id")
			is_loc = self.is_loc_loan(loan_row.get("loan_product"))

			if loan_id not in processed_loans:
				loan_doc = self.prepare_main_document(loan_row, "Loan", is_loc)
				all_documents.append(loan_doc)
				processed_loans[loan_id] = loan_doc
			else:
				loan_doc = processed_loans[loan_id]

			disbursement_doc = self.prepare_loan_disbursement(loan_row, loan_doc, is_loc)
			disbursement_doc["_loan_row"] = loan_row
			all_documents.append(disbursement_doc)

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

	def prepare_closed_loan_documents(self, loan_data):
		all_documents = []
		for index, loan_row in enumerate(loan_data):
			loan_doc = self.prepare_main_document(loan_row, "Loan", False)
			all_documents.append(loan_doc)
		return all_documents

	def prepare_loan_repayment_documents(self, repayment_data):
		documents = []
		for repayment_row in repayment_data:
			repayment_doc = self.prepare_main_document(repayment_row, "Loan Repayment")
			documents.append(repayment_doc)
		return documents

	def prepare_main_document(self, row_data, doctype, is_loc=False):
		if doctype == "Loan":
			return self._prepare_loan_doc(row_data, is_loc)
		else:
			return self._prepare_loan_repayment_doc(row_data)

	def _prepare_loan_doc(self, loan_row, is_loc=False):
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

		self.add_dynamic_fields(loan, loan_row, "Loan")
		return loan

	def _prepare_loan_repayment_doc(self, repayment_row):
		loan_details = frappe.db.get_value(
			"Loan",
			repayment_row.get("against_loan"),
			["applicant_type", "applicant", "loan_product", "company"],
			as_dict=True,
		)

		repayment = {
			"doctype": "Loan Repayment",
			"loan_repayment_id": repayment_row.get("loan_repayment_id"),
			"against_loan": repayment_row.get("against_loan"),
			"applicant_type": loan_details.applicant_type,
			"applicant": loan_details.applicant,
			"loan_product": loan_details.loan_product,
			"loan_disbursement": repayment_row.get("loan_disbursement"),
			"repayment_type": repayment_row.get("repayment_type"),
			"posting_date": repayment_row.get("posting_date"),
			"value_date": repayment_row.get("value_date") or repayment_row.get("posting_date"),
			"amount_paid": flt(repayment_row.get("amount_paid", 0)),
			"principal_amount_paid": flt(repayment_row.get("principal_amount_paid", 0)),
			"total_interest_paid": flt(repayment_row.get("total_interest_paid", 0)),
			"total_penalty_paid": flt(repayment_row.get("total_penalty_paid", 0)),
			"total_charges_paid": flt(repayment_row.get("total_charges_paid", 0)),
			"unbooked_interest_paid": flt(repayment_row.get("unbooked_interest_paid", 0)),
			"unbooked_penalty_paid": flt(repayment_row.get("unbooked_penalty_paid", 0)),
			"excess_amount": flt(repayment_row.get("excess_amount", 0)),
			"payment_account": repayment_row.get("payment_account"),
			"loan_account": repayment_row.get("loan_account"),
			"bank_account": repayment_row.get("bank_account"),
			"reference_number": repayment_row.get("reference_number"),
			"reference_date": repayment_row.get("reference_date"),
			"manual_remarks": repayment_row.get("manual_remarks"),
			"company": self.company,
			"is_imported": 1,
		}

		self.add_dynamic_fields(repayment, repayment_row, "Loan Repayment")
		return repayment

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

	def prepare_loan_interest_accrual(self, loan_row, loan_doc, disbursement_doc):
		if self.import_type == "Closed Loans":
			return []

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
		if self.import_type == "Closed Loans":
			return []

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

	def add_dynamic_fields(self, doc, row_data, doctype=None):
		loan_meta = frappe.get_meta(doctype)
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
	def import_data(self):
		self.validate()
		return self.process_import()

	def process_import(self):
		import_data = self.process_import_file(self.import_for)
		validation_results = self.validate_import_data(import_data)

		if validation_results:
			for error in validation_results:
				row = error["row"]
				error_msg = error["error"]

				if self.import_for == "Loan":
					loan_id = import_data[row - 1].get("loan_id") if row - 1 < len(import_data) else f"Row {row}"
					create_loan_import_log(
						None,
						None,
						f"Validation Error - Row {row}",
						"Failed",
						error=error_msg,
						against_loan=loan_id if loan_id and loan_id != f"Row {row}" else None,
					)
				else:
					create_loan_import_log(None, None, f"Validation Error - Row {row}", "Failed", error=error_msg)

			rows_with_errors = set()
			for error in validation_results:
				rows_with_errors.add(error["row"] - 1)

			valid_rows = []
			invalid_rows = []

			for i, row in enumerate(import_data):
				if i in rows_with_errors:
					invalid_rows.append(row)
				else:
					valid_rows.append(row)

			if not valid_rows:
				error_count = len(validation_results)
				frappe.msgprint(
					_("{0} errors. Check Loan Import Log for details. No data was imported.").format(error_count),
					indicator="orange",
				)
				return {"validation_errors": error_count, "imported_count": 0}

			error_count = len(invalid_rows)
			valid_count = len(valid_rows)

			frappe.msgprint(
				_(
					"{0} rows have validation errors and will be skipped. {1} valid rows will be imported."
				).format(error_count, valid_count),
				indicator="orange",
			)

			all_documents = self.prepare_import_documents(valid_rows)
		else:
			all_documents = self.prepare_import_documents(import_data)
			valid_count = len(import_data)

		if len(all_documents) < 50:
			if self.import_for == "Loan Repayment":
				return start_loan_repayment_import(all_documents, self.name, self.import_for)
			else:
				return start_loan_import(all_documents, self.import_type, self.name, self.import_for)
		else:
			run_now = frappe.in_test or frappe.conf.developer_mode
			if is_scheduler_inactive() and not run_now:
				frappe.throw(_("Scheduler is inactive. Cannot import data."), title=_("Scheduler Inactive"))

			job_id = f"loan_import::{self.name}"
			if not is_job_enqueued(job_id):
				if self.import_for == "Loan Repayment":
					enqueue(
						start_loan_repayment_import,
						queue="default",
						timeout=10000,
						event="loan_import",
						job_id=job_id,
						documents=all_documents,
						import_tool_name=self.name,
						import_for=self.import_for,
						now=run_now,
					)
				else:
					enqueue(
						start_loan_import,
						queue="default",
						timeout=10000,
						event="loan_import",
						job_id=job_id,
						documents=all_documents,
						import_type=self.import_type,
						import_tool_name=self.name,
						import_for=self.import_for,
						now=run_now,
					)

		return {"success_count": valid_count}

	def validate_loan_repayment_data(self, repayment_data):
		errors = []
		required_fields = [
			"loan_repayment_id",
			"against_loan",
			"posting_date",
			"amount_paid",
			"principal_amount_paid",
			"total_interest_paid",
		]

		for i, repayment in enumerate(repayment_data):
			row_errors = []

			missing_fields = [field for field in required_fields if not repayment.get(field)]
			if missing_fields:
				row_errors.append(_("Following fields are required: {0}").format(", ".join(missing_fields)))

			loan_id = repayment.get("against_loan")
			if loan_id and not frappe.db.exists("Loan", loan_id):
				row_errors.append(_("Loan '{0}' does not exist").format(loan_id))

			repayment_id = repayment.get("loan_repayment_id")
			if repayment_id and frappe.db.exists("Loan Repayment", repayment_id):
				row_errors.append(_("Loan Repayment ID '{0}' already exists").format(repayment_id))

			numeric_errors = self.validate_repayment_numeric_fields(repayment, i)
			if numeric_errors:
				row_errors.extend(numeric_errors)

			date_errors = self.validate_repayment_date_fields(repayment, i)
			if date_errors:
				row_errors.extend(date_errors)

			for error in row_errors:
				errors.append({"row": i + 1, "error": error})

		return errors

	def validate_repayment_numeric_fields(self, repayment, index):
		errors = []
		numeric_fields = [
			"amount_paid",
			"principal_amount_paid",
			"total_interest_paid",
			"total_penalty_paid",
			"total_charges_paid",
			"unbooked_interest_paid",
			"unbooked_penalty_paid",
			"excess_amount",
		]

		for field in numeric_fields:
			if repayment.get(field):
				try:
					flt(repayment[field])
				except ValueError:
					errors.append(_("Invalid numeric value for field {0}").format(field))

		return errors

	def validate_repayment_date_fields(self, repayment, index):
		errors = []
		date_fields = ["posting_date", "value_date", "reference_date"]
		for field in date_fields:
			if repayment.get(field):
				try:
					getdate(repayment[field])
				except Exception:
					errors.append(_("Invalid date format for field {0}").format(field))

		return errors


def create_loan_import_log(
	reference_doctype, reference_name, title, status, error=None, against_loan=None
):
	try:
		log = frappe.new_doc("Loan Import Log")
		log.reference_doctype = reference_doctype
		log.reference_name = reference_name
		log.title = title
		log.status = status
		if against_loan:
			log.against_loan = against_loan
		if error:
			log.error = str(error)
		log.insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep
	except Exception as e:
		frappe.log_error(f"Failed to create Loan Import Log: {str(e)}")


def start_loan_import(documents, import_type, import_tool_name, import_for):
	errors = 0
	success_count = 0
	failed_loans = []

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

	created_loans = create_loan_documents(loan_documents, import_tool_name, import_for)
	success_count += len(created_loans)

	if import_type == "Mid Tenure Loans":
		created_disbursements = create_disbursement_documents(
			disbursement_documents, created_loans, import_tool_name, import_for, failed_loans
		)

		if gl_entry_documents:
			create_gl_entries(gl_entry_documents, created_loans, import_tool_name, import_for, failed_loans)

		if interest_accrual_documents:
			create_interest_accrual_documents(
				interest_accrual_documents,
				created_loans,
				created_disbursements,
				import_tool_name,
				import_for,
				failed_loans,
			)

		if loan_demand_documents:
			create_loan_demand_documents(
				loan_demand_documents,
				created_loans,
				created_disbursements,
				import_tool_name,
				import_for,
				failed_loans,
			)

	frappe.db.commit()  # nosemgrep

	if failed_loans:
		publish_final_status(len(documents), len(documents), "partial_success")
		frappe.msgprint(
			_("Completed with {0} errors. Failed loans: {1}").format(
				len(failed_loans), ", ".join(failed_loans)
			),
			indicator="orange",
		)
	else:
		publish_final_status(len(documents), len(documents), "success")
		frappe.msgprint(
			_("Loan import completed successfully! Imported {0} loans").format(success_count),
			indicator="green",
		)

	return {"success_count": success_count, "failed_loans": failed_loans}


def create_loan_documents(loan_documents, import_tool_name, import_for):
	created_loans = {}
	for idx, loan_dict in enumerate(loan_documents):
		publish(idx, len(loan_documents), "Loan")
		loan_id = loan_dict.get("loan_id")

		if loan_id in created_loans:
			continue

		try:
			loan = frappe.get_doc(loan_dict)
			loan.flags.ignore_mandatory = True
			loan.flags.ignore_validate = True
			loan.insert(ignore_permissions=True)
			loan.submit()

			created_loans[loan_id] = loan.name
			create_loan_import_log("Loan", loan.name, f"Loan {loan_id}", "Success", against_loan=loan_id)
		except Exception as e:
			frappe.db.rollback()
			error_message = f"Error importing loan {loan_id}: {str(e)}\n{traceback.format_exc()}"
			create_loan_import_log(
				"Loan", loan_id, f"Loan {loan_id}", "Failed", error=error_message, against_loan=loan_id
			)
			frappe.log_error(f"Loan Import Error for {loan_id}: {str(e)}")

	return created_loans


def create_disbursement_documents(
	disbursement_documents, created_loans, import_tool_name, import_for, failed_loans
):
	created_disbursements = {}
	for idx, disbursement_dict in enumerate(disbursement_documents):
		loan_id = disbursement_dict.get("against_loan")
		disbursement_id = disbursement_dict.get("loan_disbursement_id")

		if not loan_id or loan_id not in created_loans:
			failed_loans.append(loan_id)
			create_loan_import_log(
				"Loan Disbursement",
				disbursement_id,
				f"Disbursement {disbursement_id}",
				"Failed",
				error=f"No matching loan found: {loan_id}",
				against_loan=loan_id,
			)
			continue

		if disbursement_id in created_disbursements:
			continue

		try:
			disbursement_dict["against_loan"] = created_loans[loan_id]
			disbursement = frappe.get_doc(disbursement_dict)
			disbursement.flags.ignore_mandatory = True
			disbursement.flags.ignore_validate = True
			disbursement.insert(ignore_permissions=True)
			disbursement.make_gl_entries = MethodType(lambda self, *a, **kw: None, disbursement)
			disbursement.status = "Submitted"
			disbursement.submit()

			created_disbursements[disbursement_id] = disbursement.name
			create_loan_import_log(
				"Loan Disbursement",
				disbursement.name,
				f"Disbursement {disbursement_id}",
				"Success",
				against_loan=loan_id,
			)

			loan_row = disbursement_dict.get("_loan_row", {})
			migration_date = loan_row.get("migration_date")

			update_demand_generated_for_repayment_schedule(
				created_loans[loan_id],
				disbursement.name,
				migration_date,
			)
		except Exception as e:
			frappe.db.rollback()
			failed_loans.append(loan_id)
			error_message = (
				f"Error importing disbursement {disbursement_id}: {str(e)}\n{traceback.format_exc()}"
			)
			create_loan_import_log(
				"Loan Disbursement",
				disbursement_id,
				f"Disbursement {disbursement_id}",
				"Failed",
				error=error_message,
				against_loan=loan_id,
			)
			frappe.log_error(f"Disbursement Import Error for {disbursement_id}: {str(e)}")

	return created_disbursements


def create_gl_entries(
	gl_entry_documents, created_loans, import_tool_name, import_for, failed_loans
):
	for idx, gl_placeholder in enumerate(gl_entry_documents):
		loan_row = gl_placeholder.get("_loan_row")
		loan_doc = gl_placeholder.get("_loan_doc")

		loan_id = loan_doc.get("loan_id")

		if not loan_id or loan_id not in created_loans or loan_id in failed_loans:
			continue

		try:
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
					create_loan_import_log(
						"GL Entry", gl_entry.name, f"GL Entry for {loan_id}", "Success", against_loan=loan_id
					)
		except Exception as e:
			frappe.db.rollback()
			failed_loans.append(loan_id)
			error_message = (
				f"Error creating GL entry for loan {loan_id}: {str(e)}\n{traceback.format_exc()}"
			)
			create_loan_import_log(
				"GL Entry",
				loan_id,
				f"GL Entry for {loan_id}",
				"Failed",
				error=error_message,
				against_loan=loan_id,
			)
			frappe.log_error(f"GL Entry Import Error for {loan_id}: {str(e)}")


def create_interest_accrual_documents(
	interest_accrual_documents,
	created_loans,
	created_disbursements,
	import_tool_name,
	import_for,
	failed_loans,
):
	for idx, accrual_dict in enumerate(interest_accrual_documents):
		loan_id = accrual_dict.get("loan")
		disbursement_id = accrual_dict.get("loan_disbursement")

		if not loan_id or loan_id not in created_loans or loan_id in failed_loans:
			continue

		if not disbursement_id or disbursement_id not in created_disbursements:
			failed_loans.append(loan_id)
			create_loan_import_log(
				"Loan Interest Accrual",
				loan_id,
				f"Interest Accrual for {loan_id}",
				"Failed",
				error=f"No matching disbursement found: {disbursement_id}",
				against_loan=loan_id,
			)
			continue

		try:
			accrual_dict["loan"] = created_loans[loan_id]
			accrual_dict["loan_disbursement"] = created_disbursements[disbursement_id]

			accrual = frappe.get_doc(accrual_dict)
			accrual.flags.ignore_mandatory = True
			accrual.flags.ignore_validate = True
			accrual.flags.ignore_gl_entries = True
			accrual.insert(ignore_permissions=True)
			accrual.make_gl_entries = MethodType(lambda self, *a, **kw: None, accrual)
			accrual.submit()
			create_loan_import_log(
				"Loan Interest Accrual",
				accrual.name,
				f"Interest Accrual for {loan_id}",
				"Success",
				against_loan=loan_id,
			)
		except Exception as e:
			frappe.db.rollback()
			failed_loans.append(loan_id)
			error_message = (
				f"Error creating interest accrual for loan {loan_id}: {str(e)}\n{traceback.format_exc()}"
			)
			create_loan_import_log(
				"Loan Interest Accrual",
				loan_id,
				f"Interest Accrual for {loan_id}",
				"Failed",
				error=error_message,
				against_loan=loan_id,
			)
			frappe.log_error(f"Interest Accrual Import Error for {loan_id}: {str(e)}")


def create_loan_demand_documents(
	loan_demand_documents,
	created_loans,
	created_disbursements,
	import_tool_name,
	import_for,
	failed_loans,
):
	for idx, demand_dict in enumerate(loan_demand_documents):
		loan_id = demand_dict.get("loan")
		disbursement_id = demand_dict.get("loan_disbursement")

		if not loan_id or loan_id not in created_loans or loan_id in failed_loans:
			continue

		if not disbursement_id or disbursement_id not in created_disbursements:
			failed_loans.append(loan_id)
			create_loan_import_log(
				"Loan Demand",
				loan_id,
				f"Loan Demand for {loan_id}",
				"Failed",
				error=f"No matching disbursement found: {disbursement_id}",
				against_loan=loan_id,
			)
			continue

		try:
			demand_dict["loan"] = created_loans[loan_id]
			demand_dict["loan_disbursement"] = created_disbursements[disbursement_id]

			demand = frappe.get_doc(demand_dict)
			demand.flags.ignore_mandatory = True
			demand.flags.ignore_validate = True
			demand.insert(ignore_permissions=True)
			demand.make_gl_entries = MethodType(lambda self, *a, **kw: None, demand)
			demand.submit()
			create_loan_import_log(
				"Loan Demand", demand.name, f"Loan Demand for {loan_id}", "Success", against_loan=loan_id
			)
		except Exception as e:
			frappe.db.rollback()
			failed_loans.append(loan_id)
			error_message = (
				f"Error creating loan demand for loan {loan_id}: {str(e)}\n{traceback.format_exc()}"
			)
			create_loan_import_log(
				"Loan Demand",
				loan_id,
				f"Loan Demand for {loan_id}",
				"Failed",
				error=error_message,
				against_loan=loan_id,
			)
			frappe.log_error(f"Loan Demand Import Error for {loan_id}: {str(e)}")


def start_loan_repayment_import(documents, import_tool_name, import_for):
	errors = 0
	created_repayments = []

	try:
		loan_import_tool = frappe.new_doc("Loan Import Tool")

		values = []
		now = frappe.utils.now()
		user = frappe.session.user

		repayment_meta = frappe.get_meta("Loan Repayment")
		standard_fields = [
			"name",
			"loan_repayment_id",
			"against_loan",
			"applicant_type",
			"applicant",
			"loan_product",
			"loan_disbursement",
			"repayment_type",
			"posting_date",
			"value_date",
			"amount_paid",
			"principal_amount_paid",
			"total_interest_paid",
			"total_penalty_paid",
			"total_charges_paid",
			"unbooked_interest_paid",
			"unbooked_penalty_paid",
			"excess_amount",
			"payment_account",
			"loan_account",
			"bank_account",
			"reference_number",
			"reference_date",
			"manual_remarks",
			"company",
			"is_imported",
			"creation",
			"modified",
			"owner",
			"modified_by",
		]

		custom_fields = [
			field.fieldname for field in repayment_meta.fields if field.fieldname.startswith("custom_")
		]

		all_fields = standard_fields + custom_fields

		for idx, repayment_dict in enumerate(documents):
			publish(idx, len(documents), "Loan Repayment")

			try:
				name = repayment_dict.get("loan_repayment_id")

				value_tuple = (
					name,
					repayment_dict.get("loan_repayment_id"),
					repayment_dict.get("against_loan"),
					repayment_dict.get("applicant_type"),
					repayment_dict.get("applicant"),
					repayment_dict.get("loan_product"),
					repayment_dict.get("loan_disbursement"),
					repayment_dict.get("repayment_type", "Regular"),
					repayment_dict.get("posting_date"),
					repayment_dict.get("value_date"),
					flt(repayment_dict.get("amount_paid", 0)),
					flt(repayment_dict.get("principal_amount_paid", 0)),
					flt(repayment_dict.get("total_interest_paid", 0)),
					flt(repayment_dict.get("total_penalty_paid", 0)),
					flt(repayment_dict.get("total_charges_paid", 0)),
					flt(repayment_dict.get("unbooked_interest_paid", 0)),
					flt(repayment_dict.get("unbooked_penalty_paid", 0)),
					flt(repayment_dict.get("excess_amount", 0)),
					repayment_dict.get("payment_account"),
					repayment_dict.get("loan_account"),
					repayment_dict.get("bank_account"),
					repayment_dict.get("reference_number"),
					repayment_dict.get("reference_date"),
					repayment_dict.get("manual_remarks"),
					repayment_dict.get("company"),
					1,
					now,
					now,
					user,
					user,
				)

				for custom_field in custom_fields:
					value_tuple += (repayment_dict.get(custom_field),)

				values.append(value_tuple)
				created_repayments.append(name)
				create_loan_import_log(
					"Loan Repayment",
					name,
					f"Repayment {name}",
					"Success",
					against_loan=repayment_dict.get("against_loan"),
				)

			except Exception as e:
				errors += 1
				error_message = f"Error importing repayment {repayment_dict.get('loan_repayment_id')}: {str(e)}\n{traceback.format_exc()}"
				create_loan_import_log(
					"Loan Repayment",
					repayment_dict.get("loan_repayment_id"),
					f"Repayment {repayment_dict.get('loan_repayment_id')}",
					"Failed",
					error=error_message,
					against_loan=repayment_dict.get("against_loan"),
				)
				frappe.log_error(f"Loan Repayment Import Error: {str(e)}")

		if values:
			frappe.db.bulk_insert("Loan Repayment", fields=all_fields, values=values)

			for repayment_name in created_repayments:
				frappe.db.set_value("Loan Repayment", repayment_name, "docstatus", 1)

			frappe.db.commit()  # nosemgrep

		if errors > 0:
			publish_final_status(len(documents), len(documents), "partial_success")
			frappe.msgprint(
				_("Loan Repayment import completed with {0} errors.").format(errors), indicator="orange"
			)
		else:
			publish_final_status(len(documents), len(documents), "success")
			frappe.msgprint(_("Loan Repayment import completed successfully!"), indicator="green")

	except Exception as e:
		frappe.db.rollback()
		error_message = f"Loan Repayment Import Error: {str(e)}\n{traceback.format_exc()}"
		frappe.log_error(error_message)
		publish_final_status(len(documents), len(documents), "partial_success")
		frappe.msgprint(
			_("Loan Repayment import completed with errors. Check Loan Import Log for details."),
			indicator="orange",
		)

	return created_repayments


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
	frappe.db.commit()  # nosemgrep


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
def download_template(
	doctype,
	import_for=None,
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

	if import_for == "Loan":
		if import_type == "Mid Tenure Loans" and doctype == "Loan":
			static_fields = [
				"Loan Disbursement ID",
				"Migration Date",
				"Principal Outstanding Amount",
				"Interest Outstanding Amount",
				"Penalty Outstanding Amount",
				"Additional Outstanding Amount",
				"Charge Outstanding Amount",
			]
	elif import_for == "Loan Repayment" and doctype == "Loan Repayment":
		pass

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

	if import_for == "Loan Repayment":
		frappe.response.filename = "loan_repayment_import_template.csv"
	else:
		frappe.response.filename = "loan_import_template.csv"

	frappe.response.filecontent = output.getvalue().encode("utf-8")
	frappe.response.type = "download"
