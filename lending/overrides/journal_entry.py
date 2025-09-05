from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry

from lending.loan_management.utils import loan_accounting_enabled


class CustomJournalEntry(JournalEntry):
	def make_gl_entries(self, *args, **kwargs):
		if loan_accounting_enabled(self.company):
			super().make_gl_entries(*args, **kwargs)
