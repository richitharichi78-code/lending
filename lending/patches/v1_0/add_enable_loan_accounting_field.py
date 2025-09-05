import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("Custom Field", {"dt": "Company", "fieldname": "enable_loan_accounting"}):
		custom_fields = {
			"Company": [
				{
					"fieldname": "enable_loan_accounting",
					"label": "Enable Loan Accounting",
					"fieldtype": "Check",
					"insert_after": "loan_settings",
					"default": 1,
				}
			]
		}
		create_custom_fields(custom_fields, update=True)
