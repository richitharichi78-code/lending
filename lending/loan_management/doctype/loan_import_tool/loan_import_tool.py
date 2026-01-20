# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import csv
import io
import json
from types import MethodType

import frappe
from frappe import _
from frappe.core.doctype.data_import.exporter import Exporter
from frappe.core.doctype.data_import.importer import Importer, ImportFile
from frappe.model.document import Document
from frappe.utils import flt, getdate
from frappe.utils.background_jobs import is_job_enqueued
from frappe.utils.scheduler import is_scheduler_inactive


class LoanImportTool(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		company: DF.Link
		create_missing_customers: DF.Check
		data_import: DF.Link | None
		import_file: DF.Attach | None
		import_for: DF.Literal["Loan", "Loan Repayment"]
		loan_import_type: DF.Literal["Mid Tenure Loans", "Closed Loans"]
		status: DF.Literal["Pending", "Success", "Partial Success", "Error", "Timed Out"]
	# end: auto-generated types

	def validate(self):
		if not self.company:
			frappe.throw(_("Please select Company"))

		if not self.import_file:
			self.data_import = None

	def get_static_mandatory_labels(self):
		if self.import_for == "Loan" and self.loan_import_type == "Mid Tenure Loans":
			return [
				"Loan Disbursement ID", "Principal Outstanding Amount", "Interest Outstanding Amount",
				"Penalty Outstanding Amount", "Additional Outstanding Amount", "Charge Outstanding Amount",
			]
		return []

	def prevalidate_extra_columns(self, di_name: str, parsed_file) -> bool:
		static_labels = self.get_static_mandatory_labels()
		if not static_labels:
			return True

		self.current_data_import_name = di_name
		row_extras = self.read_extra_columns(parsed_file)
		failed = False

		for row_no, extras in row_extras.items():
			missing = [lbl for lbl in static_labels if extras.get(lbl) in (None, "")]
			if missing:
				failed = True
				self.mark_row_failed(
					row_no,
					"Missing mandatory fields: " + ", ".join(missing),
					title="Mandatory",
				)

		if failed:
			if frappe.db.exists("Data Import", di_name):
				frappe.db.set_value("Data Import", di_name, "status", "Error", update_modified=False)
			self.db_set("status", "Error", update_modified=False)
			return False

		return True

	@frappe.whitelist()
	def start_import(self):
		self.check_permission("write")

		if not self.import_file:
			frappe.throw(_("Please attach import file"))

		run_now = frappe.in_test or frappe.conf.developer_mode

		target_doctype = self.get_target_doctype()
		parsed_file = ImportFile(target_doctype, self.import_file, import_type="Insert New Records")
		payload_count = len(parsed_file.get_payloads_for_import())

		di = self.create_data_import(
			reference_doctype=target_doctype,
			import_type="Insert New Records",
			payload_count=payload_count,
			submit_after_import=1,
		)

		self.db_set("data_import", di.name, update_modified=False)
		self.db_set("status", "Pending", update_modified=False)

		if payload_count > 100 and not run_now:
			if is_scheduler_inactive():
				frappe.throw(_("Scheduler is inactive. Cannot import data."))

			job_id = f"loan_import_tool||{self.doctype}||{self.name}"
			if not is_job_enqueued(job_id):
				frappe.enqueue(
					run_loan_import_tool_job,
					queue="long",
					timeout=10000,
					job_id=job_id,
					event="data_import",
					tool_doctype=self.doctype,
					tool_name=self.name,
					data_import_name=di.name,
					now=run_now,
					enqueue_after_commit=True,
				)

			return {"data_import": di.name, "queued": 1}

		self.run_import_now(di.name)
		return {"data_import": di.name, "queued": 0}

	@frappe.whitelist()
	def get_import_logs(self):
		self.check_permission("read")
		if not self.data_import:
			return []
		return frappe.get_all(
			"Data Import Log",
			fields=["row_indexes", "success", "docname", "log_index", "messages", "exception"],
			filters={"data_import": self.data_import},
			order_by="log_index",
		)

	def run_import_now(self, data_import_name: str):
		target_doctype = self.get_target_doctype()

		if target_doctype == "Loan Repayment":
			self.import_loan_repayments(data_import_name)
			self.set_final_status_from_logs(data_import_name)
			return

		if target_doctype == "Loan":
			self.import_loans(data_import_name)
			self.set_final_status_from_logs(data_import_name)
			return

		frappe.throw(f"Unsupported Import For: {self.import_for}")

	def set_final_status_from_logs(self, data_import_name: str):
		fail = frappe.db.count(
			"Data Import Log",
			{"data_import": data_import_name, "success": 0}
		) or 0

		success = frappe.db.count(
			"Data Import Log",
			{"data_import": data_import_name, "success": 1}
		) or 0

		if fail == 0:
			final_status = "Success"
		elif success == 0:
			final_status = "Error"
		else:
			final_status = "Partial Success"

		if frappe.db.exists("Data Import", data_import_name):
			frappe.db.set_value(
				"Data Import",
				data_import_name,
				"status",
				final_status,
				update_modified=False,
			)

		self.db_set("status", final_status, update_modified=False)
		frappe.db.commit() # nosemgrep

	def import_loan_repayments(self, data_import_name: str):
		di = frappe.get_doc("Data Import", data_import_name)
		importer = Importer("Loan Repayment", data_import=di)
		importer.import_data()

		frappe.publish_realtime("data_import_refresh", {"data_import": di.name}, user=frappe.session.user)

	def import_loans(self, data_import_name: str):
		di = frappe.get_doc("Data Import", data_import_name)

		parsed_file = ImportFile("Loan", self.import_file, import_type="Insert New Records")
		payloads = parsed_file.get_payloads_for_import()

		if not self.prevalidate_extra_columns(di.name, parsed_file):
			frappe.publish_realtime("data_import_refresh", {"data_import": di.name}, user=frappe.session.user)
			return

		row_values = self.read_all_columns(parsed_file)
		row_extras = self.read_extra_columns(parsed_file)
		row_to_loan_id, row_to_loan_product = self.build_row_maps(payloads)

		if getattr(self, "create_missing_customers", 0):
			self.create_missing_customer_records(payloads)

		self.current_data_import_name = di.name

		importer = Importer("Loan", data_import=di)
		self.patch_importer_skip_existing_loans(importer)
		importer.import_data()

		loan_product_cache: dict[str, bool] = {}
		row_is_loc = {
			row_no: self.is_line_of_credit(row_to_loan_product.get(row_no), loan_product_cache)
			for row_no in row_to_loan_product
		}

		logs = self.get_data_import_logs(di.name)

		for log in logs:
			if not log.get("success"):
				continue

			row_no = self.get_row_no_from_log(log)
			if not row_no:
				continue

			loan_name = log.get("docname") or row_to_loan_id.get(row_no)
			if not loan_name:
				continue

			is_loc = bool(row_is_loc.get(row_no))
			values = row_values.get(row_no) or {}
			extras = row_extras.get(row_no) or {}

			loan_already_existed = self.record_existed_before_import("Loan", loan_name, di.name)

			if self.loan_import_type == "Mid Tenure Loans" and loan_already_existed:
				existing_status = frappe.db.get_value("Loan", loan_name, "status")
				if existing_status == "Closed":
					self.mark_row_failed(row_no, f"Loan {loan_name} is already Closed. Cannot import as Mid Tenure Loans.")
					continue

			try:
				if not loan_already_existed:
					self.apply_loan_fields(loan_name, values, is_loc=is_loc)

				self.create_related_docs_for_row(
					loan_name=loan_name,
					row_values=values,
					row_extras=extras,
					is_loc=is_loc,
					row_no=row_no,
					loan_already_existed=loan_already_existed,
				)

			except Exception:
				if not loan_already_existed and frappe.db.exists("Loan", loan_name):
					try:
						frappe.get_doc("Loan", loan_name).cancel()
						frappe.delete_doc("Loan", loan_name, force=1, ignore_permissions=True)
					except Exception:
						pass
				continue

		frappe.publish_realtime("data_import_refresh", {"data_import": di.name}, user=frappe.session.user)

	def create_missing_customer_records(self, payloads):
		default_customer_group = frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
		default_territory = frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"

		for payload in payloads:
			doc = payload.doc or {}
			applicant_type = (doc.get("applicant_type") or doc.get("Applicant Type") or "").strip()
			applicant = (doc.get("applicant") or doc.get("Applicant") or "").strip()

			if not applicant:
				applicant = (doc.get("customer") or doc.get("Customer") or "").strip()

			if applicant_type and applicant_type != "Customer":
				continue
			if not applicant:
				continue

			existing = frappe.db.get_value("Customer", applicant, "name")
			if existing:
				continue

			try:
				customer = frappe.new_doc("Customer")
				customer.customer_name = applicant
				customer.customer_type = "Individual"
				customer.customer_group = default_customer_group
				customer.territory = default_territory
				customer.flags.ignore_mandatory = True
				customer.insert(ignore_permissions=True)
			except Exception as e:
				row_no = payload.rows[0].row_number if getattr(payload, "rows", None) and payload.rows else None
				if row_no:
					self.mark_row_failed(row_no, f"Customer create failed for '{applicant}': {e}")
				else:
					frappe.log_error(title="Loan Import Tool: Customer create failed", message=str(e))
				continue

	def apply_loan_fields(self, loan_name: str, values: dict, is_loc: bool):
		def pick(*keys):
			for k in keys:
				v = values.get(k)
				if v not in ("", None):
					return v
			return None

		posting_date = pick("posting_date", "Posting Date")
		loan_amount = pick("loan_amount", "Loan Amount")

		updates = {}
		if not is_loc:
			updates.update(
				{
					"repayment_method": pick("repayment_method", "Repayment Method"),
					"repayment_frequency": pick("repayment_frequency", "Repayment Frequency"),
					"repayment_periods": pick("repayment_periods", "Repayment Periods"),
					"repayment_start_date": pick("repayment_start_date", "Repayment Start Date"),
					"disbursement_date": pick("disbursement_date", "Disbursement Date"),
				}
			)
		else:
			updates.update(
				{
					"limit_applicable_start": posting_date,
					"maximum_limit_amount": flt(loan_amount),
				}
			)

		valid_columns = set(frappe.get_meta("Loan").get_valid_columns())
		to_set = {k: v for k, v in updates.items() if k in valid_columns and v is not None}
		if not to_set:
			return

		loan = frappe.get_doc("Loan", loan_name)
		for k, v in to_set.items():
			loan.set(k, v)

		loan.save(ignore_permissions=True)

	def create_related_docs_for_row(
		self,
		loan_name: str,
		row_values: dict,
		row_extras: dict,
		is_loc: bool,
		row_no: int,
		loan_already_existed: bool = False,
	):
		def pick(d, *keys):
			for k in keys:
				v = d.get(k)
				if v not in ("", None):
					return v
			return None

		if self.loan_import_type == "Closed Loans":
			frappe.db.set_value("Loan", loan_name, "status", "Closed", update_modified=False)
			if loan_already_existed:
				self.mark_row_failed(row_no, f"Duplicate Loan: {loan_name} found")
			return

		loan_vals = frappe.db.get_value(
			"Loan",
			loan_name,
			["company", "posting_date", "disbursement_date", "migration_date", "status"],
			as_dict=True,
		)
		if not loan_vals:
			self.mark_row_failed(row_no, f"Loan not found: {loan_name}")
			raise frappe.ValidationError("Loan not found")

		if self.loan_import_type == "Mid Tenure Loans" and loan_vals.get("status") == "Closed":
			self.mark_row_failed(row_no, f"Loan {loan_name} is already Closed. Cannot import as Mid Tenure Loans.")
			raise frappe.ValidationError("Loan is closed")

		loan_row = {
			"posting_date": pick(row_values, "posting_date", "Posting Date"),
			"disbursement_date": pick(row_values, "disbursement_date", "Disbursement Date")
			or loan_vals.get("disbursement_date")
			or loan_vals.get("posting_date"),
			"disbursed_amount": flt(pick(row_values, "disbursed_amount", "Disbursed Amount")),
			"repayment_method": pick(row_values, "repayment_method", "Repayment Method"),
			"repayment_frequency": pick(row_values, "repayment_frequency", "Repayment Frequency"),
			"repayment_periods": pick(row_values, "repayment_periods", "Repayment Periods"),
			"repayment_start_date": pick(row_values, "repayment_start_date", "Repayment Start Date"),
		}

		migration_date = (
			pick(row_extras, "Migration Date", "migration_date")
			or pick(row_values, "Migration Date", "migration_date")
			or loan_vals.get("migration_date")
		)
		migration_date = getdate(migration_date) if migration_date else None

		loan_disbursement_id = pick(row_extras, "Loan Disbursement ID", "loan_disbursement_id")
		if not loan_disbursement_id:
			self.mark_row_failed(row_no, "Missing Loan Disbursement ID")
			raise frappe.ValidationError("Missing Loan Disbursement ID")

		if frappe.db.exists("Loan Disbursement", {"loan_disbursement_id": loan_disbursement_id}):
			reasons = []
			if loan_already_existed:
				reasons.append(f"Duplicate Loan: {loan_name} found")
			reasons.append(f"Duplicate Loan Disbursement: {loan_disbursement_id} found")
			self.mark_row_failed(row_no, "\n".join(reasons))
			raise frappe.ValidationError("Duplicate Loan Disbursement")

		principal_outstanding = flt(pick(row_extras, "Principal Outstanding Amount"))
		interest_outstanding = flt(pick(row_extras, "Interest Outstanding Amount"))
		penalty_outstanding = flt(pick(row_extras, "Penalty Outstanding Amount"))
		additional_outstanding = flt(pick(row_extras, "Additional Outstanding Amount"))
		charge_outstanding = flt(pick(row_extras, "Charge Outstanding Amount"))

		disb_name = self.create_loan_disbursement(
			loan_company=loan_vals.get("company"),
			loan_name=loan_name,
			loan_row=loan_row,
			loan_disbursement_id=loan_disbursement_id,
			is_loc=is_loc,
		)

		if not migration_date:
			return

		try:
			self.create_interest_accruals(
				loan_name=loan_name,
				disbursement_name=disb_name,
				migration_date=migration_date,
				principal_outstanding=principal_outstanding,
				interest_outstanding=interest_outstanding,
				penalty_outstanding=penalty_outstanding,
				additional_outstanding=additional_outstanding,
			)

			self.create_demands(
				loan_name=loan_name,
				disbursement_name=disb_name,
				migration_date=migration_date,
				principal_outstanding=principal_outstanding,
				interest_outstanding=interest_outstanding,
				penalty_outstanding=penalty_outstanding,
				additional_outstanding=additional_outstanding,
				charge_outstanding=charge_outstanding,
			)

			update_demand_generated_for_repayment_schedule(loan_name, disb_name, migration_date)

		except Exception as e:
			self.mark_row_failed(row_no, f"Failed creating related docs for {loan_name}: {e}")
			raise

	def create_loan_disbursement(
		self,
		loan_company: str,
		loan_name: str,
		loan_row: dict,
		loan_disbursement_id: str,
		is_loc: bool,
	) -> str:
		disbursement_dict = {
			"doctype": "Loan Disbursement",
			"loan_disbursement_id": loan_disbursement_id,
			"company": loan_company,
			"against_loan": loan_name,
			"disbursement_date": loan_row.get("disbursement_date"),
			"disbursed_amount": flt(loan_row.get("disbursed_amount")),
			"posting_date": loan_row.get("posting_date") or loan_row.get("disbursement_date"),
		}

		if is_loc:
			disbursement_dict.update(
				{
					"repayment_method": loan_row.get("repayment_method"),
					"repayment_frequency": loan_row.get("repayment_frequency"),
					"repayment_periods": loan_row.get("repayment_periods"),
					"repayment_start_date": loan_row.get("repayment_start_date"),
				}
			)

		disb = frappe.get_doc(disbursement_dict)
		disb.flags.ignore_validate = True
		disb.flags.ignore_mandatory = True
		disb.insert(ignore_permissions=True)
		disb.status = "Submitted"
		disb.submit()
		return disb.name

	def create_interest_accruals(
		self,
		loan_name: str,
		disbursement_name: str,
		migration_date,
		principal_outstanding: float,
		interest_outstanding: float,
		penalty_outstanding: float,
		additional_outstanding: float,
	):
		if frappe.db.exists(
			"Loan Interest Accrual",
			{"loan": loan_name, "loan_disbursement": disbursement_name, "posting_date": migration_date},
		):
			return

		loan_vals = frappe.db.get_value(
			"Loan",
			loan_name,
			[
				"company",
				"applicant_type",
				"applicant",
				"loan_product",
				"rate_of_interest",
				"disbursement_date",
				"posting_date",
			],
			as_dict=True,
		)
		if not loan_vals:
			return

		base = {
			"doctype": "Loan Interest Accrual",
			"company": loan_vals.company,
			"loan": loan_name,
			"loan_disbursement": disbursement_name,
			"applicant_type": loan_vals.applicant_type,
			"applicant": loan_vals.applicant,
			"loan_product": loan_vals.loan_product,
			"accrual_type": "Regular",
			"posting_date": migration_date,
			"accrual_date": migration_date,
			"start_date": loan_vals.disbursement_date or loan_vals.posting_date,
			"last_accrual_date": migration_date,
			"rate_of_interest": flt(loan_vals.rate_of_interest or 0),
			"is_term_loan": 1,
		}

		if flt(interest_outstanding) > 0:
			doc = frappe.get_doc(
				{
					**base,
					"interest_type": "Normal Interest",
					"base_amount": flt(principal_outstanding),
					"interest_amount": flt(interest_outstanding),
					"accrued_interest": flt(interest_outstanding),
					"total_pending_interest": flt(interest_outstanding),
					"additional_interest_amount": 0,
					"penalty_amount": 0,
					"accrued_penalty": 0,
					"total_pending_penalty": 0,
				}
			)
			doc.flags.ignore_validate = True
			doc.flags.ignore_mandatory = True
			doc.insert(ignore_permissions=True)
			doc.submit()

		total_penal = flt(penalty_outstanding) + flt(additional_outstanding)
		if total_penal > 0:
			doc = frappe.get_doc(
				{
					**base,
					"interest_type": "Penal Interest",
					"additional_interest_amount": total_penal,
					"base_amount": 0,
					"interest_amount": 0,
					"accrued_interest": 0,
					"total_pending_interest": 0,
				}
			)
			doc.flags.ignore_validate = True
			doc.flags.ignore_mandatory = True
			doc.insert(ignore_permissions=True)
			doc.submit()

	def create_demands(
		self,
		loan_name: str,
		disbursement_name: str,
		migration_date,
		principal_outstanding: float,
		interest_outstanding: float,
		penalty_outstanding: float,
		additional_outstanding: float,
		charge_outstanding: float,
	):
		loan_vals = frappe.db.get_value(
			"Loan",
			loan_name,
			["company", "applicant_type", "applicant", "loan_product", "disbursement_date", "posting_date"],
			as_dict=True,
		)
		if not loan_vals:
			return

		components = [
			("EMI", "Principal", principal_outstanding),
			("EMI", "Interest", interest_outstanding),
			("Penalty", "Penalty", penalty_outstanding),
			("Additional Interest", "Additional Interest", additional_outstanding),
			("Charges", "Charges", charge_outstanding),
		]

		for demand_type, demand_subtype, amount in components:
			amount = flt(amount)
			if amount <= 0:
				continue

			if frappe.db.exists(
				"Loan Demand",
				{
					"loan": loan_name,
					"loan_disbursement": disbursement_name,
					"posting_date": migration_date,
					"demand_type": demand_type,
					"demand_subtype": demand_subtype,
				},
			):
				continue

			doc = frappe.get_doc(
				{
					"doctype": "Loan Demand",
					"company": loan_vals.company,
					"loan": loan_name,
					"loan_disbursement": disbursement_name,
					"applicant_type": loan_vals.applicant_type,
					"applicant": loan_vals.applicant,
					"loan_product": loan_vals.loan_product,
					"posting_date": migration_date,
					"demand_date": migration_date,
					"disbursement_date": loan_vals.disbursement_date or loan_vals.posting_date,
					"is_term_loan": 1,
					"demand_type": demand_type,
					"demand_subtype": demand_subtype,
					"demand_amount": amount,
					"outstanding_amount": amount,
					"paid_amount": 0,
					"waived_amount": 0,
					"status": "Unpaid",
				}
			)

			doc.flags.ignore_validate = True
			doc.flags.ignore_mandatory = True
			doc.insert(ignore_permissions=True)
			doc.submit()

	def patch_importer_skip_existing_loans(self, importer):
		orig_insert = importer.insert_record

		def patched_insert_record(self_importer, doc):
			loan_name = None
			if isinstance(doc, dict):
				loan_name = (doc.get("name") or doc.get("loan_id") or "").strip()

			if loan_name and frappe.db.exists("Loan", loan_name):
				return frappe.get_doc("Loan", loan_name)

			try:
				return orig_insert(doc)
			except frappe.DuplicateEntryError:
				if loan_name and frappe.db.exists("Loan", loan_name):
					return frappe.get_doc("Loan", loan_name)
				raise

		importer.insert_record = MethodType(patched_insert_record, importer)

	def get_data_import_logs(self, data_import_name: str):
		return frappe.get_all(
			"Data Import Log",
			fields=["row_indexes", "success", "docname", "log_index", "messages", "exception"],
			filters={"data_import": data_import_name},
			order_by="log_index",
		)

	def get_row_no_from_log(self, log: dict):
		row_indexes = json.loads(log.get("row_indexes") or "[]")
		return row_indexes[0] if row_indexes else None

	def read_extra_columns(self, import_file) -> dict:
		cols = import_file.header.columns
		idxs, headers = [], []

		for c in cols:
			if c.skip_import:
				idxs.append(c.index)
				headers.append(c.header_title)

		out = {}
		for row in import_file.data:
			values = {}
			for idx, header in zip(idxs, headers, strict=False):
				v = row.data[idx] if idx < len(row.data) else None
				values[header] = None if v in ("", None) else v
			out[row.row_number] = values
		return out

	def read_all_columns(self, import_file) -> dict:
		cols = import_file.header.columns
		headers = [c.header_title for c in cols]

		out = {}
		for row in import_file.data:
			values = {}
			for i, header in enumerate(headers):
				v = row.data[i] if i < len(row.data) else None
				values[header] = None if v in ("", None) else v
			out[row.row_number] = values
		return out

	def build_row_maps(self, payloads):
		row_to_loan_id = {}
		row_to_loan_product = {}

		for payload in payloads:
			if not payload.doc:
				continue

			loan_id = (payload.doc.get("loan_id") or "").strip() if payload.doc.get("loan_id") else None
			loan_product = payload.doc.get("loan_product")

			for r in payload.rows:
				row_to_loan_id[r.row_number] = loan_id
				row_to_loan_product[r.row_number] = loan_product

		return row_to_loan_id, row_to_loan_product

	def is_line_of_credit(self, loan_product, cache: dict) -> bool:
		if not loan_product:
			return False
		if loan_product in cache:
			return cache[loan_product]
		schedule_type = frappe.db.get_value("Loan Product", loan_product, "repayment_schedule_type")
		cache[loan_product] = (schedule_type == "Line of Credit")
		return cache[loan_product]

	def create_data_import(self, reference_doctype: str, import_type: str, payload_count: int, submit_after_import: int):
		di = frappe.get_doc(
			{
				"doctype": "Data Import",
				"reference_doctype": reference_doctype,
				"import_type": import_type,
				"import_file": self.import_file,
				"google_sheets_url": None,
				"submit_after_import": 1 if submit_after_import else 0,
				"mute_emails": 1,
				"payload_count": payload_count,
			}
		).insert(ignore_permissions=True)
		return di

	def mark_row_failed(self, row_no: int, message: str, title: str = "Error"):
		data_import_name = getattr(self, "current_data_import_name", None)
		if not data_import_name:
			return

		new_item = {"title": title, "message": message}
		target_row_indexes = json.dumps([row_no])

		log_name = frappe.db.get_value(
			"Data Import Log",
			{"data_import": data_import_name, "row_indexes": target_row_indexes},
			"name",
		)

		if not log_name:
			frappe.get_doc(
				{
					"doctype": "Data Import Log",
					"data_import": data_import_name,
					"success": 0,
					"messages": json.dumps([new_item]),
					"row_indexes": target_row_indexes,
				}
			).insert(ignore_permissions=True)
			return

		log = frappe.get_doc("Data Import Log", log_name)
		existing = log.get("messages") or "[]"
		try:
			arr = json.loads(existing) if isinstance(existing, str) else existing
			if not isinstance(arr, list):
				arr = []
		except Exception:
			arr = []

		arr.append(new_item)
		log.messages = json.dumps(arr)
		log.success = 0
		log.flags.ignore_validate = True
		log.save(ignore_permissions=True)

	def get_target_doctype(self):
		return "Loan Repayment" if self.import_for == "Loan Repayment" else "Loan"

	def record_existed_before_import(self, doctype: str, docname: str, data_import_name: str) -> bool:
		created = frappe.db.get_value(doctype, docname, "creation")
		di_created = frappe.db.get_value("Data Import", data_import_name, "creation")
		return bool(created and di_created and created < di_created)


def run_loan_import_tool_job(tool_doctype: str, tool_name: str, data_import_name: str):
	tool = frappe.get_doc(tool_doctype, tool_name)

	try:
		tool.db_set("status", "Pending", update_modified=False)
		tool.run_import_now(data_import_name)

	except Exception as e:
		frappe.db.rollback()

		status = "Error"
		if "timeout" in str(e).lower():
			status = "Timed Out"

		if frappe.db.exists("Data Import", data_import_name):
			frappe.db.set_value("Data Import", data_import_name, "status", "Error", update_modified=False)

		if frappe.db.exists(tool_doctype, tool_name):
			frappe.db.set_value(tool_doctype, tool_name, "status", status, update_modified=False)

		frappe.log_error(title="Loan Import Tool failed", message=str(e))

	finally:
		frappe.flags.in_import = False
		frappe.publish_realtime("data_import_refresh", {"data_import": data_import_name}, user=frappe.session.user)


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


@frappe.whitelist()
def download_template(
	doctype,
	import_for=None,
	loan_import_type=None,
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
		if loan_import_type == "Mid Tenure Loans" and doctype == "Loan":
			static_fields = [
				"Loan Disbursement ID",
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

	if csv_array and csv_array[0] and static_fields:
		csv_array[0].extend(static_fields)

	output = io.StringIO()
	writer = csv.writer(output)
	writer.writerows(csv_array)

	frappe.response.filename = (
		"loan_repayment_import_template.csv" if import_for == "Loan Repayment" else "loan_import_template.csv"
	)
	frappe.response.filecontent = output.getvalue().encode("utf-8")
	frappe.response.type = "download"
