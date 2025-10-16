from erpnext.accounts.doctype.journal_entry.journal_entry import (
	JournalEntry as ERPNextJournalEntry,
)

from lending.loan_management.utils import loan_accounting_enabled


class JournalEntry(ERPNextJournalEntry):
	def make_gl_entries(self, *args, **kwargs):
		if not loan_accounting_enabled(self.company):
			return
		super().make_gl_entries(*args, **kwargs)
