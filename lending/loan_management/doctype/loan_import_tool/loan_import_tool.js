// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Import Tool", {
	setup: function(frm) {
		frappe.realtime.on("loan_import_progress", (data) => {
			if (!frm.doc.import_in_progress) {
				frm.dashboard.reset();
				frm.doc.import_in_progress = true;
			}

			if (data.count == data.total) {
				setTimeout(() => {
					frm.doc.import_in_progress = false;
					frm.refresh_fields();
					frm.page.clear_indicator();
					frm.dashboard.hide_progress();

					if (data.status === "partial_success") {
						frappe.msgprint({
							title: __("Import Completed with Errors"),
							message: __("Loan import completed with some errors. Check Error Log for details."),
							indicator: "orange"
						});
					}
					// else {
					// 	frappe.msgprint(__("Loan import has been completed successfully!"));
					// }
				}, 1500);
				return;
			}

			frm.dashboard.show_progress(data.title, (data.count / data.total) * 100, data.message);
			frm.page.set_indicator(__("Import In Progress"), "orange");
		});
	},

	refresh: function(frm) {
		frm.disable_save();

		frm.page.set_primary_action(__("Import Loans"), () => {
			if (!frm.doc.import_file) {
				frappe.msgprint(__("Please attach import file first"));
				return;
			}

			frm.page.set_primary_action(__("Importing..."));

			return frm.call({
				doc: frm.doc,
				method: "import_loans",
				freeze: true,
				freeze_message: __("Importing Loans...")
			}).then(() => {
				frm.page.set_primary_action(__("Import Loans"));
			});
		});

		frm.add_custom_button(__("Download Template"), () => {
			frm.trigger("download_template");
		});
	},

	download_template: function(frm) {
		const dialog = new frappe.ui.Dialog({
			title: __('Select Fields for Template'),
			fields: [
				{
					fieldtype: 'HTML',
					fieldname: 'custom_fields_html',
					options: '<div class="alert alert-info">Select custom fields to include in the template:</div>'
				},
				{
					fieldtype: 'MultiCheck',
					fieldname: 'custom_fields',
					options: [],
					columns: 2
				}
			],
			primary_action_label: __('Download Template'),
			primary_action: function() {
				const selected_fields = dialog.get_values().custom_fields || [];
				dialog.hide();
				frm.events.download_template_with_selected_fields(frm, selected_fields);
			}
		});

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Custom Field",
				filters: { dt: "Loan" },
				fields: ["fieldname", "label"]
			},
			callback: function(r) {
				if (r.message) {
					const field_options = r.message.map(field => ({
						label: field.label || field.fieldname,
						value: field.fieldname,
						checked: true
					}));

					dialog.fields_dict.custom_fields.df.options = field_options;
					dialog.fields_dict.custom_fields.refresh();
				}
				dialog.show();
			}
		});
	},

	download_template_with_selected_fields: function(frm, custom_fields) {
		const method = "/api/method/lending.loan_management.doctype.loan_import_tool.loan_import_tool.loan_template_download";
		const export_fields = {
			"Loan": [
				"loan_id", "applicant_type", "applicant", "loan_product", "loan_amount",
				"posting_date", "company", "repayment_method", "repayment_frequency",
				"repayment_periods", "rate_of_interest", "penalty_charges_rate",
				"disbursement_date", "disbursed_amount", "repayment_start_date", "total_principal_paid",
				"total_interest_payable", "total_payment", "written_off_amount", "status"
			],
		};

		if (custom_fields && custom_fields.length > 0) {
			export_fields["Loan"] = export_fields["Loan"].concat(custom_fields);
		}

		open_url_post(method, {
			doctype: "Loan",
			import_type: frm.doc.import_type,
			export_records: "blank_template",
			export_fields: export_fields
		});
	},

	import_type: function(frm) {
		frm.set_value("import_file", "");
	},

	import_file: function(frm) {
		if (frm.doc.import_file) {
			const valid_extensions = ['.csv', '.xlsx', '.xls'];
			const file_extension = '.' + frm.doc.import_file.split('.').pop().toLowerCase();

			if (!valid_extensions.includes(file_extension)) {
				frappe.msgprint({
					title: __('Invalid File'),
					message: __('Please upload CSV or Excel file only.'),
					indicator: 'red'
				});
				frm.set_value('import_file', '');
			}
		}
	}
});