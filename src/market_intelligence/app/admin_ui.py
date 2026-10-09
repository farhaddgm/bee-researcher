from __future__ import annotations

import json
from pathlib import Path


_UX_WRITING_CATALOG_PATH = Path(__file__).with_name("ux_writing_catalog.json")
_UX_WRITING_CATALOG_ADDITIONS_PATH = Path(__file__).with_name("ux_writing_catalog_additions.json")
try:
    _UX_WRITING_CATALOG = json.loads(_UX_WRITING_CATALOG_PATH.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    # The UI remains usable with its built-in bilingual catalog if an
    # installation is missing the generated spreadsheet snapshot.
    _UX_WRITING_CATALOG = {}
try:
    # Rows appended to the connected UX Writing sheet are kept as a small
    # additive snapshot.  Merging here makes the sheet the runtime source
    # without rewriting the reviewed base catalog on every update.
    _UX_WRITING_CATALOG.update(
        json.loads(_UX_WRITING_CATALOG_ADDITIONS_PATH.read_text(encoding="utf-8"))
    )
except (OSError, json.JSONDecodeError):
    pass
_UX_WRITING_CATALOG_JSON = json.dumps(
    _UX_WRITING_CATALOG,
    ensure_ascii=False,
    separators=(",", ":"),
)



_ADMIN_MODULES = [('__ADMIN_BLOCK_0__', 'style', '', '00-core.css'), ('__ADMIN_BLOCK_1__', 'style', '', '01-Keep.css'), ('__ADMIN_BLOCK_2__', 'script', '', '02-Only.js'), ('__ADMIN_BLOCK_3__', 'style', '', '03-Vazirmatn.css'), ('__ADMIN_BLOCK_4__', 'script', '', '04-Independent.js'), ('__ADMIN_BLOCK_5__', 'script', '', '05-The.js'), ('__ADMIN_BLOCK_6__', 'script', '', '06-Keep.js'), ('__ADMIN_BLOCK_7__', 'script', '', '07-MI-076.js'), ('__ADMIN_BLOCK_8__', 'script', '', '08-MI-UX-004.js'), ('__ADMIN_BLOCK_9__', 'script', '', '09-Owner.js'), ('__ADMIN_BLOCK_10__', 'style', '', '10-MI-143.css'), ('__ADMIN_BLOCK_11__', 'script', '', '11-MI-143.js'), ('__ADMIN_BLOCK_12__', 'script', '', '12-MI-086.js'), ('__ADMIN_BLOCK_13__', 'script', '', '13-Bee.js'), ('__ADMIN_BLOCK_14__', 'script', '', '14-MI-090.js'), ('__ADMIN_BLOCK_15__', 'script', '', '15-MI-093.js'), ('__ADMIN_BLOCK_16__', 'script', '', '16-MI-095.js'), ('__ADMIN_BLOCK_17__', 'style', '', '17-core.css'), ('__ADMIN_BLOCK_18__', 'script', '', '18-MI-096.js'), ('__ADMIN_BLOCK_19__', 'script', '', '19-MI-098.js'), ('__ADMIN_BLOCK_20__', 'script', '', '20-MI-099.js'), ('__ADMIN_BLOCK_21__', 'script', '', '21-MI-117.js'), ('__ADMIN_BLOCK_22__', 'script', '', '22-MI-114.js'), ('__ADMIN_BLOCK_23__', 'style', '', '23-MI-119.css'), ('__ADMIN_BLOCK_24__', 'script', '', '24-MI-119.js'), ('__ADMIN_BLOCK_25__', 'script', '', '25-MI-112.js'), ('__ADMIN_BLOCK_26__', 'style', '', '26-MI-125.css'), ('__ADMIN_BLOCK_27__', 'script', '', '27-Keep.js'), ('__ADMIN_BLOCK_28__', 'style', '', '28-Owner-controlled.css'), ('__ADMIN_BLOCK_29__', 'script', '', '29-MI-UX-001.js'), ('__ADMIN_BLOCK_30__', 'script', '', '30-MI-UX-002.js'), ('__ADMIN_BLOCK_31__', 'style', '', '31-MI-132.css'), ('__ADMIN_BLOCK_32__', 'script', '', '32-MI-132.js'), ('__ADMIN_BLOCK_33__', 'style', '', '33-MI-141.css'), ('__ADMIN_BLOCK_34__', 'script', '', '34-MI-141.js'), ('__ADMIN_BLOCK_35__', 'style', '', '35-MI-144.css'), ('__ADMIN_BLOCK_36__', 'style', '', '36-I-059.css'), ('__ADMIN_BLOCK_37__', 'script', '', '37-I-059.js'), ('__ADMIN_BLOCK_38__', 'script', '', '38-Support.js'), ('__ADMIN_BLOCK_39__', 'style', '', '39-MI-167.css'), ('__ADMIN_BLOCK_40__', 'script', '', '40-MI-167.js'), ('__ADMIN_BLOCK_41__', 'style', '', '41-MI-182.css'), ('__ADMIN_BLOCK_42__', 'script', '', '42-MI-181.js'), ('__ADMIN_BLOCK_43__', 'style', '', '43-MI-206.css'), ('__ADMIN_BLOCK_44__', 'script', '', '44-MI-206.js'), ('__ADMIN_BLOCK_45__', 'script', '', '45-MI-208.js'), ('__ADMIN_BLOCK_46__', 'script', '', '46-MI-UX-003.js'), ('__ADMIN_BLOCK_47__', 'script', '', '47-One.js'), ('__ADMIN_BLOCK_48__', 'script', '', '48-MI-LOCALE-ATOMIC.js'), ('__ADMIN_BLOCK_49__', 'script', '', '49-MI-LOCALE-RECONCILE.js'), ('__ADMIN_BLOCK_50__', 'script', '', '50-MI-207.js'), ('__ADMIN_BLOCK_51__', 'style', ' id="admin-ux-v325-style"', '51-admin-ux-v325-style.css'), ('__ADMIN_BLOCK_52__', 'script', '', '52-MI-205.js'), ('__ADMIN_BLOCK_53__', 'style', ' id="support-v3-style"', '53-support-v3-style.css'), ('__ADMIN_BLOCK_54__', 'script', ' id="support-v3-stabilizer"', '54-support-v3-stabilizer.js'), ('__ADMIN_BLOCK_55__', 'script', ' id="admin-performance-guards"', '55-admin-performance-guards.js'), ('__ADMIN_BLOCK_56__', 'style', ' id="admin-layout-stability"', '56-admin-layout-stability.css'), ('__ADMIN_BLOCK_57__', 'style', ' id="source-observability-style"', '57-source-observability-style.css'), ('__ADMIN_BLOCK_58__', 'script', ' id="source-observability-ui"', '58-source-observability-ui.js'), ('__ADMIN_BLOCK_59__', 'style', ' id="user-portal-access-style"', '59-user-portal-access-style.css'), ('__ADMIN_BLOCK_60__', 'script', ' id="user-portal-access-ui"', '60-user-portal-access-ui.js'), ('__ADMIN_BLOCK_61__', 'style', ' id="admin-button-pattern-v1"', '61-admin-button-pattern-v1.css'), ('__ADMIN_BLOCK_62__', 'style', ' id="admin-support-final"', '62-admin-support-final.css'), ('__ADMIN_BLOCK_63__', 'script', ' id="admin-final-hardening"', '63-admin-final-hardening.js'), ('__ADMIN_BLOCK_64__', 'style', ' id="admin-button-pattern-v2"', '64-admin-button-pattern-v2.css'), ('__ADMIN_BLOCK_65__', 'script', ' id="admin-button-pattern-v2-script"', '65-admin-button-pattern-v2-script.js'), ('__ADMIN_BLOCK_66__', 'script', ' id="admin-support-scope"', '66-admin-support-scope.js'), ('__ADMIN_BLOCK_67__', 'style', ' id="support-ticket-v4-style"', '67-support-ticket-v4-style.css'), ('__ADMIN_BLOCK_68__', 'script', ' id="support-ticket-v4"', '68-support-ticket-v4.js'), ('__ADMIN_BLOCK_69__', 'script', ' id="support-dialog-accessibility-v1"', '69-support-dialog-accessibility-v1.js'), ('__ADMIN_BLOCK_70__', 'style', ' id="support-ticket-v4-pending-style"', '70-support-ticket-v4-pending-style.css'), ('__ADMIN_BLOCK_71__', 'script', ' id="support-ticket-v4-ownership-guard"', '71-support-ticket-v4-ownership-guard.js'), ('__ADMIN_BLOCK_72__', 'script', ' id="admin-ui-capability-cleanup-v1"', '72-admin-ui-capability-cleanup-v1.js'), ('__ADMIN_BLOCK_73__', 'style', ' id="sidebar-collapse-layout-v1"', '73-sidebar-collapse-layout-v1.css'), ('__ADMIN_BLOCK_74__', 'style', ' id="assistants-locale-layout-v1"', '74-assistants-locale-layout-v1.css'), ('__ADMIN_BLOCK_75__', 'style', ' id="media-workflow-v2-style"', '75-media-workflow-v2-style.css'), ('__ADMIN_BLOCK_76__', 'script', ' id="media-workflow-v2"', '76-media-workflow-v2.js'), ('__ADMIN_BLOCK_77__', 'script', ' id="project-relevance-settings"', '77-project-relevance-settings.js'), ('__ADMIN_BLOCK_78__', 'style', ' id="google-login-style"', '78-google-login-style.css'), ('__ADMIN_BLOCK_79__', 'script', ' id="google-login-layer"', '79-google-login-layer.js'), ('__ADMIN_BLOCK_80__', 'script', ' id="google-access-layer"', '80-google-access-layer.js')]
_MODULE_ROOT = Path(__file__).with_name('admin_ui_modules')
ADMIN_HTML = (_MODULE_ROOT / 'shell.html').read_text(encoding='utf-8')
for _token, _kind, _attrs, _name in _ADMIN_MODULES:
    ADMIN_HTML = ADMIN_HTML.replace(_token, '<' + _kind + _attrs + '>' + (_MODULE_ROOT / _name).read_text(encoding='utf-8') + '</' + _kind + '>')

ADMIN_HTML = ADMIN_HTML.replace("__UX_WRITING_CATALOG__", _UX_WRITING_CATALOG_JSON).replace(
    '<script id="google-login-layer">',
    '<script id="ai-model-settings-layer">'
    + Path(__file__).with_name("admin_model_settings.js").read_text(encoding="utf-8")
    + '</script>\n<script id="google-login-layer">',
).replace(
    '</head>',
    '<style id="product-diagnostics-styles">'
    + Path(__file__).with_name("admin_product.css").read_text(encoding="utf-8")
    + '</style></head>', 1,
).replace(
    '</body>',
    '<script id="product-diagnostics-controller">'
    + Path(__file__).with_name("admin_product.js").read_text(encoding="utf-8")
    + '</script></body>', 1,
).replace(
    '</head>',
    '<style id="backoffice-ui-contract">'
    + Path(__file__).with_name("backoffice_ui.css").read_text(encoding="utf-8")
    + '</style></head>', 1,
).replace(
    '</body>',
    '<script id="backoffice-ui-controller">'
    + Path(__file__).with_name("backoffice_ui.js").read_text(encoding="utf-8")
    + '</script></body>', 1,
).replace(
    '</head>',
    '<style id="contenter-business-styles">'
    + Path(__file__).with_name("admin_contenter.css").read_text(encoding="utf-8")
    + Path(__file__).with_name("admin_research_context.css").read_text(encoding="utf-8")
    + '</style></head>', 1,
).replace(
    '</body>',
    '<script id="contenter-business-controller">'
    + Path(__file__).with_name("admin_contenter.js").read_text(encoding="utf-8")
    + Path(__file__).with_name("admin_research_context.js").read_text(encoding="utf-8")
    + '</script></body>', 1,
)

# One shared login/identity controller replaces the legacy delayed layers.
ADMIN_HTML = ADMIN_HTML.replace('</head>', '<style id="admin-declarations">' + (_MODULE_ROOT / 'declarations.css').read_text(encoding='utf-8') + '</style></head>', 1)
from app.auth_ui import decorate_auth_html
ADMIN_HTML = decorate_auth_html(ADMIN_HTML, admin=True)
