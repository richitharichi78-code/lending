# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class LoanImportLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		against_loan: DF.Data | None
		error: DF.Code | None
		reference_doctype: DF.Link | None
		reference_name: DF.Data | None
		status: DF.Literal["", "Success", "Failed"]
		title: DF.Data | None
	# end: auto-generated types

	pass
