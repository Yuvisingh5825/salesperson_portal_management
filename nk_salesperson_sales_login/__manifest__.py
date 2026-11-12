{
    "name": "Field Salesperson Portal",
    "version": "19.0.1.3.0",
    "category": "Sales",
    "summary": "Salesperson login with private quotations, reporting, expenses, surveys and live location tracking",
    "author": "NeemKaroli Consulting LLP",
    "website": "https://neemkaroliconsulting.com/",
    "images": ["static/description/banner.png"],
    "depends": ["base",
        "web",
        "sale_management",
        "sale_margin",
        "hr",],
    "data": [
        "security/security.xml",
        "security/nk_salesperson_menu_security.xml",
        "security/nk_salesperson_rules.xml",
        "security/ir.model.access.csv",
        "data/data.xml",
        "data/tracking_data.xml",
        "views/hr_employee_views.xml",
        "views/sale_order_views.xml",
        "views/menu_views.xml",
        "views/nk_sales_report_views.xml",
        "views/nk_salesperson_expense_views.xml",
        "views/survey_views.xml",
        "views/survey_templates.xml",
        "views/templates.xml",
        "views/tracking_views.xml",
        "views/tracking_templates.xml",
        "report/nk_salesperson_statement_report.xml"
    ],
    "assets": {
        "web.assets_frontend": [
            "nk_salesperson_sales_login/static/src/css/nk_salesperson.css"
        ]
    },
    "installable": True,
    "application": True,
    "license": "LGPL-3"
}
