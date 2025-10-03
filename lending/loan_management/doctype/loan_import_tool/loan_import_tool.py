# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate
from frappe.utils.background_jobs import enqueue, is_job_enqueued
from frappe.utils.csvutils import read_csv_content
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
		show_only_failed_logs: DF.Check
	# end: auto-generated types

	def validate(self):
		"""Validate the import file and parameters"""
		if not self.company:
			frappe.throw(_("Please select Company"))

	def onload(self):
		"""Load loan import summary"""
		summary = self.get_loan_import_summary()
		self.set_onload("loan_import_summary", summary)

	def get_loan_import_summary(self):
		"""Get summary of existing loans"""
		companies = frappe.get_all("Company", fields=["name as company"])
		summary = {}

		for company in companies:
			company_name = company.company

			# Active loans
			active_loans = frappe.get_all(
				"Loan",
				filters={"company": company_name, "docstatus": 1, "status": ["!=", "Closed"]},
				fields=["count(name) as total_loans", "sum(loan_amount) as total_amount"],
			)

			# Closed loans
			closed_loans = frappe.get_all(
				"Loan",
				filters={"company": company_name, "docstatus": 1, "status": "Closed"},
				fields=["count(name) as total_loans", "sum(loan_amount) as total_amount"],
			)

			summary[company_name] = {
				"active_loans": active_loans[0] if active_loans else {},
				"closed_loans": closed_loans[0] if closed_loans else {},
			}

		return summary

	def get_loan_field_mapping(self):
		"""Dynamically get all field names and labels from Loan doctype"""
		loan_meta = frappe.get_meta("Loan")
		field_mapping = {}

		# Add all standard fields
		for field in loan_meta.fields:
			if field.fieldname and field.label:
				# Map label to fieldname (remove special characters and make case insensitive)
				clean_label = (
					field.label.strip()
					.lower()
					.replace(" ", "_")
					.replace("/", "_")
					.replace("(%)", "")
					.replace("(", "")
					.replace(")", "")
				)
				field_mapping[clean_label] = field.fieldname

				# Also map the original label
				field_mapping[field.label.strip().lower()] = field.fieldname

				# Map fieldname itself
				field_mapping[field.fieldname.lower()] = field.fieldname

		# Add common variations
		common_variations = {
			"loan_product": "loan_product",
			"loanproduct": "loan_product",
			"applicant_type": "applicant_type",
			"applicanttype": "applicant_type",
			"applicant": "applicant",
			"loan_amount": "loan_amount",
			"loanamount": "loan_amount",
			"posting_date": "posting_date",
			"postingdate": "posting_date",
			"company": "company",
			"repayment_method": "repayment_method",
			"repaymentmethod": "repayment_method",
			"repayment_frequency": "repayment_frequency",
			"repaymentfrequency": "repayment_frequency",
			"repayment_periods": "repayment_periods",
			"repaymentperiods": "repayment_periods",
			"rate_of_interest": "rate_of_interest",
			"rateofinterest": "rate_of_interest",
			"interest_rate": "rate_of_interest",
			"penalty_charges_rate": "penalty_charges_rate",
			"penaltychargesrate": "penalty_charges_rate",
			"penalty_rate": "penalty_charges_rate",
			"repayment_start_date": "repayment_start_date",
			"repaymentstartdate": "repayment_start_date",
			"total_principal_paid": "total_principal_paid",
			"totalprincipalpaid": "total_principal_paid",
			"total_interest_payable": "total_interest_payable",
			"totalinterestpayable": "total_interest_payable",
			"total_payment": "total_payment",
			"totalpayment": "total_payment",
			"written_off_amount": "written_off_amount",
			"writtenoffamount": "written_off_amount",
			"status": "status",
			"disbursement_date": "disbursement_date",
			"disbursementdate": "disbursement_date",
		}

		field_mapping.update(common_variations)
		return field_mapping

	def normalize_field_names(self, loan_data):
		"""Normalize field names in loan data using dynamic mapping"""
		field_mapping = self.get_loan_field_mapping()
		normalized_data = []

		for loan_row in loan_data:
			normalized_row = {}

			for csv_field, value in loan_row.items():
				if not csv_field or not value:
					continue

				# Clean the CSV field name for matching
				clean_csv_field = (
					csv_field.strip()
					.lower()
					.replace(" ", "_")
					.replace("/", "_")
					.replace("(%)", "")
					.replace("(", "")
					.replace(")", "")
				)

				# Find the matching fieldname
				matching_field = None

				# First try exact match with cleaned field
				if clean_csv_field in field_mapping:
					matching_field = field_mapping[clean_csv_field]
				else:
					# Try partial matching for common patterns
					for mapped_field, fieldname in field_mapping.items():
						if clean_csv_field in mapped_field or mapped_field in clean_csv_field:
							matching_field = fieldname
							break

				# If no match found, keep the original field (could be custom field)
				if matching_field:
					normalized_row[matching_field] = value
				else:
					normalized_row[csv_field] = value

			normalized_data.append(normalized_row)

		return normalized_data

	def process_import_file(self):
		"""Process the uploaded import file"""
		try:
			import_file = frappe.get_doc("File", {"file_url": self.import_file})
			file_content = import_file.get_content()
			file_name = import_file.file_name

			if file_name.endswith(".csv"):
				loan_data = self.parse_csv_content(file_content)
			elif file_name.endswith((".xlsx", ".xls")):
				loan_data = self.parse_excel_content(import_file)
			else:
				frappe.throw(_("Unsupported file format. Please upload CSV or Excel file."))

			# Normalize field names
			return self.normalize_field_names(loan_data)

		except Exception as e:
			frappe.throw(_("Error processing import file: {0}").format(str(e)))

	def parse_csv_content(self, content):
		"""Parse CSV content and return structured data"""
		rows = read_csv_content(content)
		if not rows or len(rows) < 2:
			frappe.throw(_("No data found in the file"))

		headers = [header.strip() for header in rows[0]]
		loan_data = []

		for i, row in enumerate(rows[1:], 1):
			if not any(row):  # skip empty rows
				continue

			loan_row = {}
			for idx, header in enumerate(headers):
				if idx < len(row) and row[idx] is not None:
					loan_row[header] = row[idx].strip() if isinstance(row[idx], str) else str(row[idx])

			loan_data.append(loan_row)

		return loan_data

	def parse_excel_content(self, import_file):
		"""Parse Excel content and return structured data"""
		rows = read_xlsx_file_from_attached_file(file_content=import_file.get_content())
		if not rows or len(rows) < 2:
			frappe.throw(_("No data found in the file"))

		headers = [str(header).strip() if header is not None else "" for header in rows[0]]
		loan_data = []

		for i, row in enumerate(rows[1:], 1):
			if not any(row):  # skip empty rows
				continue

			loan_row = {}
			for idx, header in enumerate(headers):
				if idx < len(row) and row[idx] is not None:
					value = row[idx]
					if isinstance(value, (str, int, float)):
						loan_row[header] = str(value).strip()
					else:
						loan_row[header] = str(value)

			loan_data.append(loan_row)

		return loan_data

	def validate_loan_data(self, loan_data):
		"""Validate loan data before processing"""
		required_fields = [
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
			"repayment_start_date",
			"total_principal_paid",
			"total_interest_payable",
			"total_payment",
			"written_off_amount",
			"status",
		]

		for i, loan in enumerate(loan_data):
			# Validate all required fields
			missing_fields = []
			for field in required_fields:
				if not loan.get(field):
					missing_fields.append(field)

			if missing_fields:
				frappe.throw(
					_("Row {0}: Following fields are required: {1}").format(i + 1, ", ".join(missing_fields))
				)

			# Set default company if not provided (though it should be required now)
			if not loan.get("company"):
				loan["company"] = self.company

			# Validate customer exists or create if enabled
			applicant_type = loan.get("applicant_type", "Customer")
			applicant = loan.get("applicant")

			if applicant and not frappe.db.exists(applicant_type, applicant):
				if self.create_missing_customers and applicant_type == "Customer":
					self.create_customer(applicant)
				else:
					frappe.throw(_("Row {0}: {1} {2} does not exist").format(i + 1, applicant_type, applicant))

			# Validate numeric fields
			numeric_fields = [
				"loan_amount",
				"rate_of_interest",
				"penalty_charges_rate",
				"total_principal_paid",
				"total_interest_payable",
				"total_payment",
				"written_off_amount",
			]

			for field in numeric_fields:
				if loan.get(field):
					try:
						flt(loan[field])
					except ValueError:
						frappe.throw(_("Row {0}: {1} must be a valid number").format(i + 1, field))

			# Validate date fields
			date_fields = ["posting_date", "repayment_start_date", "disbursement_date"]
			for field in date_fields:
				if loan.get(field):
					try:
						getdate(loan[field])
					except Exception:
						frappe.throw(_("Row {0}: {1} must be a valid date (YYYY-MM-DD)").format(i + 1, field))

	def create_customer(self, customer_name):
		"""Create missing customer"""
		try:
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
		except Exception as e:
			frappe.throw(_("Failed to create customer {0}: {1}").format(customer_name, str(e)))

	def prepare_loan_documents(self, loan_data):
		"""Prepare all loan-related documents based on import type"""
		all_documents = []

		for loan_row in loan_data:
			documents = self.prepare_single_loan_documents(loan_row)
			all_documents.extend(documents)

		return all_documents

	def prepare_single_loan_documents(self, loan_row):
		"""Prepare documents for a single loan"""
		documents = []

		# Base loan document
		loan_doc = self.prepare_loan_doc(loan_row)
		documents.append(loan_doc)

		# Loan Disbursement for both import types
		documents.extend(self.prepare_loan_disbursement(loan_row, loan_doc))

		return documents

	def prepare_loan_doc(self, loan_row):
		"""Prepare the main Loan document"""
		loan = {
			"doctype": "Loan",
			"company": loan_row.get("company") or self.company,
			"loan_product": loan_row.get("loan_product"),
			"applicant_type": loan_row.get("applicant_type", "Customer"),
			"applicant": loan_row.get("applicant"),
			"loan_amount": flt(loan_row.get("loan_amount")),
			"repayment_method": loan_row.get("repayment_method", "Repay Fixed Amount per Period"),
			"repayment_frequency": loan_row.get("repayment_frequency", "Monthly"),
			"repayment_periods": loan_row.get("repayment_periods"),
			"rate_of_interest": flt(loan_row.get("rate_of_interest", 0)),
			"penalty_charges_rate": flt(loan_row.get("penalty_charges_rate", 0)),
			"posting_date": loan_row.get("posting_date") or nowdate(),
			"repayment_start_date": loan_row.get("repayment_start_date") or nowdate(),
			"is_term_loan": 1,
			"status": loan_row.get("status", "Disbursed")
			if self.import_type == "Mid Tenure Loans"
			else "Closed",
			"disbursement_date": loan_row.get("disbursement_date") or nowdate(),
			"total_principal_paid": flt(loan_row.get("total_principal_paid", 0)),
			"total_interest_payable": flt(loan_row.get("total_interest_payable", 0)),
			"total_payment": flt(loan_row.get("total_payment", 0)),
			"written_off_amount": flt(loan_row.get("written_off_amount", 0)),
			"custom_loan_import": 1,  # Flag to identify imported loans
		}

		# Add all other fields dynamically (including custom fields)
		self.add_dynamic_fields(loan, loan_row)

		return loan

	def prepare_loan_disbursement(self, loan_row, loan_doc):
		"""Prepare Loan Disbursement document"""
		documents = []

		disbursement = {
			"doctype": "Loan Disbursement",
			"company": loan_doc.get("company"),
			"against_loan": "TEMP_LOAN",  # Placeholder that will be replaced with actual loan name
			"disbursement_date": loan_doc.get("disbursement_date"),
			"disbursed_amount": flt(loan_doc.get("loan_amount")),
			"posting_date": loan_doc.get("posting_date"),
			"custom_loan_import": 1,
		}
		documents.append(disbursement)

		return documents

	def add_dynamic_fields(self, doc, row_data):
		"""Dynamically add all fields from import data that aren't already set"""
		loan_meta = frappe.get_meta("Loan")
		existing_fields = set(doc.keys())

		for field, value in row_data.items():
			if field and value is not None and field not in existing_fields:
				# Check if this field exists in Loan doctype (could be custom field)
				if loan_meta.has_field(field) or field.startswith("custom_"):
					# Handle different data types
					if isinstance(value, str):
						value = value.strip()
						# Try to convert to appropriate type
						try:
							if "." in value:
								doc[field] = flt(value)
							else:
								doc[field] = int(value)
						except (ValueError, TypeError):
							doc[field] = value
					else:
						doc[field] = value

	@frappe.whitelist()
	def import_loans(self):
		"""Main method to import loans"""
		self.validate()

		# Process import file
		loan_data = self.process_import_file()

		# Validate loan data
		self.validate_loan_data(loan_data)

		# Prepare all documents
		all_documents = self.prepare_loan_documents(loan_data)

		if len(all_documents) < 50:
			return start_loan_import(all_documents, self.import_type)
		else:
			job_id = f"loan_import::{self.name}"

			if not is_job_enqueued(job_id):
				enqueue(
					start_loan_import,
					queue="default",
					timeout=6000,
					event="loan_import",
					job_id=job_id,
					documents=all_documents,
					import_type=self.import_type,
					now=frappe.conf.developer_mode or frappe.in_test,
				)


def start_loan_import(documents, import_type):
	"""Background job to import loan documents"""
	errors = 0
	created_documents = []

	# Separate Loan documents from child documents
	loan_documents = [doc for doc in documents if doc.get("doctype") == "Loan"]
	disbursement_documents = [doc for doc in documents if doc.get("doctype") == "Loan Disbursement"]

	loan_mapping = {}  # Store mapping of placeholder to actual loan names

	# Step 1: Create and submit all Loan documents
	for idx, loan_dict in enumerate(loan_documents):
		try:
			publish(idx, len(documents), "Loan")

			# Create loan document
			loan = frappe.get_doc(loan_dict)
			loan.flags.ignore_mandatory = True
			loan.flags.ignore_validate = True
			loan.insert(ignore_permissions=True)

			# Submit loan
			loan.submit()
			frappe.db.commit()

			# Store the actual loan name for reference
			actual_loan_name = loan.name
			loan_mapping["TEMP_LOAN"] = actual_loan_name
			created_documents.append(actual_loan_name)

			frappe.msgprint(_("Created and submitted Loan: {0}").format(actual_loan_name))

		except Exception as e:
			errors += 1
			frappe.db.rollback()
			frappe.log_error(f"Loan creation failed: {str(e)}")
			frappe.msgprint(_("Error creating loan {0}: {1}").format(idx + 1, str(e)))

	# Step 2: Create all Loan Disbursement documents with proper loan references
	for idx, disbursement_dict in enumerate(disbursement_documents):
		try:
			publish(len(loan_documents) + idx, len(documents), "Loan Disbursement")

			# Update against_loan reference to use actual loan name
			if disbursement_dict.get("against_loan") in loan_mapping:
				disbursement_dict["against_loan"] = loan_mapping[disbursement_dict.get("against_loan")]

			# Create Loan Disbursement document
			disbursement = frappe.get_doc(disbursement_dict)
			disbursement.flags.ignore_mandatory = True
			disbursement.flags.ignore_validate = True
			disbursement.insert(ignore_permissions=True)
			disbursement.submit()
			frappe.db.commit()
			created_documents.append(disbursement.name)

			frappe.msgprint(
				_("Created Loan Disbursement for loan: {0}").format(disbursement_dict["against_loan"])
			)

		except Exception as e:
			errors += 1
			frappe.db.rollback()
			frappe.log_error(f"Loan Disbursement creation failed: {str(e)}")
			frappe.msgprint(_("Error creating Loan Disbursement: {0}").format(str(e)))

	if errors:
		frappe.msgprint(
			_("Completed with {0} errors. Check {1} for details.").format(
				errors, "<a href='/app/Error Log' class='variant-click'>Error Log</a>"
			),
			indicator="orange",
		)
	else:
		frappe.msgprint(
			_("Loan import completed successfully! Created {0} documents.").format(len(created_documents)),
			indicator="green",
		)

	return created_documents


def publish(index, total, doctype):
	"""Publish real-time progress"""
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


@frappe.whitelist()
def get_import_logs(docname: str):
	frappe.has_permission("Loan Import Tool", throw=True)

	return frappe.get_all(
		"Data Import Log",
		fields=["success", "docname", "messages", "exception", "row_indexes"],
		filters={"data_import": docname},
		limit_page_length=5000,
		order_by="log_index",
	)
