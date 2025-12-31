from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.controllers.accounts_controller import AccountsController

from lending.loan_management.utils import loan_accounting_enabled


class LoanController(AccountsController):
	def make_gl_entries(self, *args, **kwargs):
		if not loan_accounting_enabled(self.company):
			return

		# Call ERPNext's native GL entry function directly
		return make_gl_entries(*args, **kwargs)

	# def make_credit_note_demand(self, *args, **kwargs):
	# 	if not loan_accounting_enabled(self.company):
	# 		return

	# 	from lending.loan_management.doctype.loan_demand.loan_demand import (
	# 		make_credit_note as make_credit_note_demand
	# 	)
	# 	return make_credit_note_demand(*args, **kwargs)

	# def make_credit_note_disbursement(self, *args, **kwargs):
	# 	if not loan_accounting_enabled(self.company):
	# 		return

	# 	from lending.loan_management.doctype.loan_disbursement.loan_disbursement import (
	# 		make_credit_note as make_credit_note_disbursement
	# 	)
	# 	return make_credit_note_disbursement(*args, **kwargs)
