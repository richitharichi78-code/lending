# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import os
import tempfile

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import random_string

from lending.tests.test_utils import init_customers, init_loan_products, master_init


class TestLoanImportTool(IntegrationTestCase):

	def setUp(self):
		master_init()
		init_loan_products()
		init_customers()

	def create_test_csv_file(self, content, filename):
		with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
			f.write(content)
		temp_path = f.name

		with open(temp_path, "rb") as f:
			file_doc = frappe.get_doc({
				"doctype": "File",
				"file_name": filename,
				"content": f.read(),
				"is_private": 0,
			})
			file_doc.save(ignore_permissions=True)

		os.unlink(temp_path)
		return file_doc.file_url

	def test_mid_tenure_loan_and_repayment_import(self):
		loan_id = f"TEST-MID-{random_string(5).upper()}"
		disbursement_id = f"DISB-MID-{random_string(5).upper()}"

		loan_csv = f"""Loan ID,Loan Disbursement ID,Company,Applicant Type,Applicant,Loan Product,Loan Amount,Posting Date,Disbursement Date,Disbursed Amount,Repayment Method,Repayment Frequency,Repayment Periods,Rate of Interest (%) / Year,Penalty Charges Rate,Repayment Start Date,Total Principal Paid,Total Interest Payable,Total Payable Amount,Written Off Amount,Status,Migration Date,Principal Outstanding Amount,Interest Outstanding Amount,Penalty Outstanding Amount,Additional Outstanding Amount,Charge Outstanding Amount
{loan_id},{disbursement_id},_Test Company,Customer,_Test Customer 1,Term Loan Product 4,500000,2024-01-15,2024-01-15,500000,Repay Over Number of Periods,Monthly,12,12.5,2,2024-02-15,125000,45000,545000,0,Disbursed,2024-06-15,375000,28500,3200,1500,800"""

		loan_file = self.create_test_csv_file(loan_csv, "mid_tenure_loan.csv")

		frappe.get_doc({
			"doctype": "Loan Import Tool",
			"company": "_Test Company",
			"import_for": "Loan",
			"import_type": "Mid Tenure Loans",
			"import_file": loan_file,
		}).import_data()

		self.assertTrue(frappe.db.exists("Loan", loan_id))
		self.assertTrue(
			frappe.db.exists(
				"Loan Disbursement",
				{"against_loan": loan_id}
			)
		)
		self.assertTrue(
			frappe.db.exists(
				"Loan Interest Accrual",
				{"loan": loan_id, "is_imported": 1}
			)
		)
		self.assertTrue(
			frappe.db.exists(
				"Loan Demand",
				{"loan": loan_id, "is_imported": 1}
			)
		)

		repayment_id = f"REPAY-MID-{random_string(5).upper()}"

		repayment_csv = f"""Loan Repayment ID,Against Loan,Loan Disbursement,Repayment Type,Posting Date,Value Date,Amount Paid,Principal Amount Paid,Total Interest Paid,Total Penalty Paid,Total Charges Paid,Unbooked Interest Paid,Unbooked Penalty Paid,Excess Amount,Repayment Account,Loan Account,Bank Account,Reference Number,Reference Date,Manual Remarks
{repayment_id},{loan_id},{disbursement_id},Normal Repayment,2024-07-15,2024-07-15,50000,40000,8000,1200,800,0,0,0,Payment Account - _TC,Loan Account - _TC,,REF-{random_string(8)},2024-07-15,Test repayment"""

		repayment_file = self.create_test_csv_file(repayment_csv, "mid_repayment.csv")

		frappe.get_doc({
			"doctype": "Loan Import Tool",
			"company": "_Test Company",
			"import_for": "Loan Repayment",
			"import_type": "Mid Tenure Loans",
			"import_file": repayment_file,
		}).import_data()

		self.assertTrue(frappe.db.exists("Loan Repayment", repayment_id))

		is_imported = frappe.db.get_value(
			"Loan Repayment",
			repayment_id,
			"is_imported"
		)

		self.assertTrue(is_imported)

	def test_closed_loan_and_repayments_import(self):
		loan_id = f"TEST-CLOSED-{random_string(5).upper()}"

		loan_csv = f"""Loan ID,Loan Disbursement ID,Company,Applicant Type,Applicant,Loan Product,Loan Amount,Posting Date,Disbursement Date,Disbursed Amount,Repayment Method,Repayment Frequency,Repayment Periods,Rate of Interest (%) / Year,Penalty Charges Rate,Repayment Start Date,Total Principal Paid,Total Interest Payable,Total Payable Amount,Written Off Amount,Status,Migration Date,Principal Outstanding Amount,Interest Outstanding Amount,Penalty Outstanding Amount,Additional Outstanding Amount,Charge Outstanding Amount
{loan_id},DISB-CLOSED-001,_Test Company,Customer,_Test Customer 1,Term Loan Product 4,300000,2024-02-20,2024-02-20,300000,Repay Over Number of Periods,Monthly,12,11.75,1.5,2024-03-10,300000,22000,322000,0,Closed,2024-12-31,0,0,0,0,0"""

		loan_file = self.create_test_csv_file(loan_csv, "closed_loan.csv")

		frappe.get_doc({
			"doctype": "Loan Import Tool",
			"company": "_Test Company",
			"import_for": "Loan",
			"import_type": "Closed Loans",
			"import_file": loan_file,
		}).import_data()

		self.assertTrue(frappe.db.exists("Loan", loan_id))

		repayment_ids = [
			f"REPAY-CLOSED-1-{random_string(5).upper()}",
			f"REPAY-CLOSED-2-{random_string(5).upper()}",
			f"REPAY-CLOSED-3-{random_string(5).upper()}",
		]

		repayment_csv = f"""Loan Repayment ID,Against Loan,Loan Disbursement,Repayment Type,Posting Date,Value Date,Amount Paid,Principal Amount Paid,Total Interest Paid,Total Penalty Paid,Total Charges Paid,Unbooked Interest Paid,Unbooked Penalty Paid,Excess Amount,Repayment Account,Loan Account,Bank Account,Reference Number,Reference Date,Manual Remarks
{repayment_ids[0]},{loan_id},,Normal Repayment,2024-03-10,2024-03-10,100000,90000,10000,0,0,0,0,0,Payment Account - _TC,Loan Account - _TC,,REF-1-{random_string(8)},2024-03-10,First
{repayment_ids[1]},{loan_id},,Normal Repayment,2024-04-10,2024-04-10,100000,95000,5000,0,0,0,0,0,Payment Account - _TC,Loan Account - _TC,,REF-2-{random_string(8)},2024-04-10,Second
{repayment_ids[2]},{loan_id},,Normal Repayment,2024-05-10,2024-05-10,122000,115000,7000,0,0,0,0,0,Payment Account - _TC,Loan Account - _TC,,REF-3-{random_string(8)},2024-05-10,Final"""

		repayment_file = self.create_test_csv_file(
			repayment_csv, "closed_repayments.csv"
		)

		frappe.get_doc({
			"doctype": "Loan Import Tool",
			"company": "_Test Company",
			"import_for": "Loan Repayment",
			"import_type": "Closed Loans",
			"import_file": repayment_file,
		}).import_data()

		repayment_count = frappe.db.count(
			"Loan Repayment",
			{"against_loan": loan_id, "is_imported": 1}
		)

		self.assertEqual(repayment_count, 3)
