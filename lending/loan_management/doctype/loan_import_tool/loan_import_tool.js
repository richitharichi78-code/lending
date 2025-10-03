// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt


frappe.ui.form.on("Loan Import Tool", {
	setup: function(frm) {

		// Real-time progress updates
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

					frappe.msgprint(__("Loan import has been completed successfully!"));
				}, 1500);
				return;
			}

			frm.dashboard.show_progress(data.title, (data.count / data.total) * 100, data.message);
			frm.page.set_indicator(__("Import In Progress"), "orange");
		});
	},

	refresh: function(frm) {
		frm.disable_save();

		// Load summary if not importing
		// !frm.doc.import_in_progress && frm.trigger("make_dashboard");

		// Primary action - Import Loans
		frm.page.set_primary_action(__("Import Loans"), () => {
			if (!frm.doc.import_file) {
				frappe.msgprint(__("Please attach import file first"));
				return;
			}

			return frm.call({
				doc: frm.doc,
				method: "import_loans",
				freeze: true,
				freeze_message: __("Importing Loans...")
			});
		});

		// Add button to download template
		frm.add_custom_button(__("Download Template"), () => {
			frm.trigger("download_template");
		});
	},

	download_template: function(frm) {
		// Show dialog to let user select which custom fields to include
		let dialog = new frappe.ui.Dialog({
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
				let selected_fields = dialog.get_values().custom_fields || [];
				dialog.hide();
				frm.events.download_template_with_selected_fields(frm, selected_fields);
			}
		});

		// Fetch custom fields and populate the dialog
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Custom Field",
				filters: {
					dt: "Loan"
				},
				fields: ["fieldname", "label"]
			},
			callback: function(r) {
				if (r.message) {
					let field_options = r.message.map(field => {
						return {
							label: field.label || field.fieldname,
							value: field.fieldname,
							checked: true // Auto-select all by default
						};
					});

					dialog.fields_dict.custom_fields.df.options = field_options;
					dialog.fields_dict.custom_fields.refresh();
				}
				dialog.show();
			}
		});
	},

	download_template_with_selected_fields: function(frm, custom_fields) {
		let method = "/api/method/frappe.core.doctype.data_import.data_import.download_template";

		let export_fields = {
			"Loan": [
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
				"status"
			]
		};

		// Add selected custom fields
		if (custom_fields && custom_fields.length > 0) {
			export_fields["Loan"] = export_fields["Loan"].concat(custom_fields);
		}

		open_url_post(method, {
			doctype: "Loan",
			export_records: "blank_template",
			export_fields: export_fields
		});
	},

	// make_dashboard: function(frm) {
	// 	let summary = frm.doc.__onload?.loan_import_summary;

	// 	if (summary && Object.keys(summary).length > 0) {
	// 		let section = frm.dashboard.add_section(
	// 			frappe.render_template("loan_import_tool_dashboard", {
	// 				data: summary,
	// 				company: frm.doc.company
	// 			}),
	// 			__("Loan Summary")
	// 		);

	// 		section.on("click", ".loan-link", function() {
	// 			let status = $(this).attr("data-status");
	// 			let filters = {
	// 				company: frm.doc.company,
	// 				docstatus: 1
	// 			};

	// 			if (status === "active") {
	// 				filters.status = ["!=", "Closed"];
	// 			} else {
	// 				filters.status = "Closed";
	// 			}

	// 			frappe.set_route("List", "Loan", filters);
	// 		});

	// 		frm.dashboard.show();
	// 	}
	// },

	import_type: function(frm) {
		// Reset import file when type changes
		frm.set_value("import_file", "");
	},

	import_file: function(frm) {
		// Validate file type when file is attached
		if (frm.doc.import_file) {
			let valid_extensions = ['.csv', '.xlsx', '.xls'];
			let file_extension = frm.doc.import_file.split('.').pop().toLowerCase();

			if (!valid_extensions.includes('.' + file_extension)) {
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