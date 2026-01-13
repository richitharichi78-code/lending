// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Import Tool", {
	setup(frm) {
		frappe.realtime.on("data_import_refresh", ({ data_import }) => {
			if (!frm.doc.data_import || data_import !== frm.doc.data_import) return;

			frm.import_in_progress = false;
			frm.page.clear_indicator();
			frm.dashboard.hide();
			frm.reload_doc().then(() => frm.trigger("show_import_log"));
		});

		frappe.realtime.on("data_import_progress", (data) => {
			if (!frm.doc.data_import || data.data_import !== frm.doc.data_import) return;

			frm.import_in_progress = true;

			let percent = Math.floor((data.current * 100) / data.total);
			let seconds = Math.floor(data.eta || 0);
			let minutes = Math.floor(seconds / 60);

			let eta_message =
				seconds < 60
					? __("About {0} seconds remaining", [seconds])
					: minutes === 1
						? __("About {0} minute remaining", [minutes])
						: __("About {0} minutes remaining", [minutes]);

			let message = data.skipping
				? __("Skipping {0} of {1}, {2}", [data.current, data.total, eta_message])
				: __("Importing {0} of {1}, {2}", [data.current, data.total, eta_message]);

			frm.dashboard.show_progress(__("Import Progress"), percent, message);
			frm.page.set_indicator(__("In Progress"), "orange");

			if (data.current === data.total) {
				setTimeout(() => {
					frm.reload_doc().then(() => frm.trigger("show_import_log"));
				}, 2500);
			}
		});
	},

	refresh(frm) {
		frm.page.hide_icon_group();
		if (frm.doc.status === "Success") {
			frm.page.clear_primary_action();
		} else {
			frm.page.set_primary_action(__("Start Import"), () => {
				if (!frm.doc.import_file) {
					frappe.msgprint(__("Please attach import file first"));
					return;
				}

				// Optional: prevent re-import while in progress
				if (frm.import_in_progress || frm.doc.status === "In Progress") {
					frappe.msgprint(__("Import is already in progress"));
					return;
				}

				frm.call({
					method: "start_import",
					doc: frm.doc,
					freeze: true,
					freeze_message: __("Starting import in background..."),
				}).then((r) => {
					if (r && r.message && r.message.data_import) {
						frm.set_value("data_import", r.message.data_import);
						frm.import_in_progress = true;
						frm.page.set_indicator(__("In Progress"), "orange");
						frm.reload_doc();
					}
				});
			});
		}

		// Optional: show indicator if currently running (depends on how you set status in Python)
		if (frm.import_in_progress || frm.doc.status === "Pending") {
			// do nothing
		} else if (frm.doc.status === "Partial Success") {
			frm.page.set_indicator(__("Partial Success"), "orange");
		} else if (frm.doc.status === "Error") {
			frm.page.set_indicator(__("Error"), "red");
		} else if (frm.doc.status === "Timed Out") {
			frm.page.set_indicator(__("Timed Out"), "red");
		} else if (frm.doc.status === "Success") {
			frm.page.set_indicator(__("Success"), "green");
		} else if (frm.doc.status) {
			frm.page.set_indicator(__(frm.doc.status), "blue");
		}

		frm.add_custom_button(__("Download Loan Template"), () => {
			frm.events.download_template(frm, "Loan");
		}, __("Download Template"));

		frm.add_custom_button(__("Download Loan Repayment Template"), () => {
			frm.events.download_template(frm, "Loan Repayment");
		}, __("Download Template"));

		frm.trigger("show_import_log");
	},

	loan_import_type: function(frm) {
		frm.set_value("import_file", "");
	},

	show_custom_fields_dialog(frm, target_doctype, callback) {
		const dialog = new frappe.ui.Dialog({
			title: __("Select Fields for Template"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "custom_fields_html",
					options:
						'<div class="alert alert-info">' +
						__("Select custom fields to include in the template:") +
						"</div>",
				},
				{
					fieldtype: "MultiCheck",
					fieldname: "custom_fields",
					options: [],
					columns: 2,
				},
			],
			primary_action_label: __("Download Template"),
			primary_action: function () {
				const values = dialog.get_values() || {};
				const selected_fields = values.custom_fields || [];
				dialog.hide();
				callback(selected_fields);
			},
		});

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Custom Field",
				filters: { dt: target_doctype },
				fields: ["fieldname", "label"],
			},
		}).then((r) => {
			if (r.message) {
				const field_options = r.message.map((field) => ({
					label: field.label || field.fieldname,
					value: field.fieldname,
					checked: true,
				}));

				dialog.fields_dict.custom_fields.df.options = field_options;
				dialog.fields_dict.custom_fields.refresh();
			}
			dialog.show();
		});
	},

	download_template_with_selected_fields(frm, target_doctype, base_fields, custom_fields) {
		const method =
			"/api/method/lending.loan_management.doctype.loan_import_tool.loan_import_tool.download_template";

		const export_fields = {};
		export_fields[target_doctype] = (base_fields || []).slice();

		if (custom_fields && custom_fields.length > 0) {
			export_fields[target_doctype] = export_fields[target_doctype].concat(custom_fields);
		}

		open_url_post(method, {
			doctype: target_doctype,
			import_for: frm.doc.import_for,
			loan_import_type: frm.doc.loan_import_type,
			export_records: "blank_template",
			export_fields: export_fields,
		});
	},

	download_template(frm, target_doctype) {
		const base_fields_map = {
			Loan: [
				"loan_id",
				"applicant_type",
				"applicant",
				"loan_product",
				"loan_amount",
				"posting_date",
				"migration_date",
				"company",
				"repayment_method",
				"repayment_frequency",
				"repayment_periods",
				"rate_of_interest",
				"penalty_charges_rate",
				"disbursement_date",
				"disbursed_amount",
				"repayment_start_date",
				"total_principal_paid",
				"total_interest_payable",
				"total_payment",
				"written_off_amount",
				"status",
			],
			"Loan Repayment": [
				"loan_repayment_id",
				"against_loan",
				"loan_disbursement",
				"repayment_type",
				"posting_date",
				"value_date",
				"amount_paid",
				"principal_amount_paid",
				"total_interest_paid",
				"total_penalty_paid",
				"total_charges_paid",
				"unbooked_interest_paid",
				"unbooked_penalty_paid",
				"excess_amount",
				"payment_account",
				"loan_account",
				"bank_account",
				"reference_number",
				"reference_date",
				"manual_remarks",
			],
		};

		const base_fields = base_fields_map[target_doctype] || [];

		frm.events.show_custom_fields_dialog(frm, target_doctype, (selected_fields) => {
			frm.events.download_template_with_selected_fields(frm, target_doctype, base_fields, selected_fields);
		});
	},

	import_file(frm) {
		if (!frm.doc.import_file) return;

		const valid_extensions = [".csv", ".xlsx", ".xls"];
		const file_extension = "." + frm.doc.import_file.split(".").pop().toLowerCase();

		if (!valid_extensions.includes(file_extension)) {
			frappe.msgprint({
				title: __("Invalid File"),
				message: __("Please upload CSV or Excel file only."),
				indicator: "red",
			});
			frm.set_value("import_file", "");
		}
	},

	show_import_log(frm) {
		frm.toggle_display("import_log_section", false);

		if (frm.is_new() || frm.import_in_progress) return;
		if (!frm.doc.data_import) return;

		frappe.call({
			method: "get_import_logs",
			doc: frm.doc,
		}).then((r) => {
			let logs = (r && r.message) || [];

			if (!logs.length) {
				frm.get_field("import_log_preview").$wrapper.html(
					`<div class="text-muted">${__("No logs yet")}</div>`
				);
				return;
			}

			frm.toggle_display("import_log_section", true);

			let rows = logs
				.map((log) => {
					let html = "";

					if (log.success) {
						if (log.docname) {
							html = __("Successfully imported {0}", [
								`<span class="underline">${frappe.utils.get_form_link(
									(frm.doc.import_for === "Loan Repayment" ? "Loan Repayment" : "Loan"),
									log.docname,
									true
								)}</span>`,
							]);
						} else {
							html = __("Success");
						}
					} else {
						let messages_html = "";

						if (log.messages) {
							try {
								let parsed = JSON.parse(log.messages);
								if (Array.isArray(parsed) && parsed.length) {
									messages_html = parsed
										.map((m) => {
											let title = m.title ? `<strong>${frappe.utils.escape_html(m.title)}</strong>` : "";
											let msg = m.message
												? `<div style="white-space: pre-line;">${frappe.utils.escape_html(
														m.message
													)}</div>`
												: "";
											return title + msg;
										})
										.join("");
								} else {
									messages_html = `<div style="white-space: pre-line;">${frappe.utils.escape_html(
										String(log.messages)
									)}</div>`;
								}
							} catch (e) {
								messages_html = `<div style="white-space: pre-line;">${frappe.utils.escape_html(
									String(log.messages)
								)}</div>`;
							}
						}

						if (!messages_html) messages_html = `<div>${__("Failed")}</div>`;

						if (log.exception) {
							let id = frappe.dom.get_unique_id();
							messages_html += `
								<button class="btn btn-default btn-xs" type="button"
									data-toggle="collapse" data-target="#${id}"
									aria-expanded="false" aria-controls="${id}" style="margin-top: 15px;">
									${__("Show Traceback")}
								</button>
								<div class="collapse" id="${id}" style="margin-top: 15px;">
									<div class="well">
										<pre>${frappe.utils.escape_html(log.exception)}</pre>
									</div>
								</div>`;
						}

						html = messages_html;
					}

					let indicator_color = log.success ? "green" : "red";
					let title = log.success ? __("Success") : __("Failure");

					let row_indexes = [];
					try {
						row_indexes = JSON.parse(log.row_indexes || "[]");
					} catch (e) {
						row_indexes = [];
					}

					return `<tr>
						<td>${row_indexes.join(", ")}</td>
						<td><div class="indicator ${indicator_color}">${title}</div></td>
						<td>${html}</td>
					</tr>`;
				})
				.join("");

			frm.get_field("import_log_preview").$wrapper.html(`
				<table class="table table-bordered">
					<tr class="text-muted">
						<th width="14%">${__("Row Number")}</th>
						<th width="15%">${__("Status")}</th>
						<th width="71%">${__("Message")}</th>
					</tr>
					${rows}
				</table>
			`);
		});
	},
});
