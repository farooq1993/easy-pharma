// ════════════════════════════════════════════
//  Purchase CSV Import Logic - FINAL VERSION
// ════════════════════════════════════════════
//
// Wrapped in an IIFE so that if this script is ever accidentally loaded
// twice (duplicate <script> tag, stale cached copy alongside a fresh one,
// etc.) it CANNOT throw "Identifier has already been declared" and take
// down the whole file's parsing. Functions called from inline HTML
// (onclick/onchange in purchase_import.html) are explicitly attached to
// `window` below so they keep working exactly as before.
(function() {
    'use strict';

    if (window.__csvImportInitialized) {
        console.warn('purchase.js loaded more than once — skipping re-init.');
        return;
    }
    window.__csvImportInitialized = true;

let _csvParsedItems  = [];
let _csvMissing      = [];
let isTransitioningToCsvSupplier = false;
let isTransitioningToOcrSupplier = false;

// console.log("✅ CSV Import JS Loaded");

// ── Stacked modal fix ─────────────────────────
// When "+ Add" is clicked from inside the CSV preview, quickAddModal opens
// ON TOP of csvImportModal (csvImportModal stays open in the background).
// Bootstrap doesn't always re-stack z-index correctly for a modal that
// already exists earlier in the DOM, so quickAddModal can end up rendered
// BEHIND csvImportModal's backdrop — it's technically open, just invisible.
// This forces quickAddModal (and its backdrop) above any already-open modal.
(function() {
    const quickAddEl = document.getElementById('quickAddModal');
    if (!quickAddEl) return;

    quickAddEl.addEventListener('show.bs.modal', function() {
        // Count how many modals + backdrops are already open/stacked
        const openBackdrops = document.querySelectorAll('.modal-backdrop').length;
        const baseZ = 1060 + (openBackdrops * 20);

        quickAddEl.style.zIndex = baseZ + 10;

        // The backdrop for THIS modal is created right as it shows; grab it
        // on the next tick and push it above any existing backdrop(s).
        setTimeout(() => {
            const backdrops = document.querySelectorAll('.modal-backdrop');
            const thisBackdrop = backdrops[backdrops.length - 1];
            if (thisBackdrop) thisBackdrop.style.zIndex = baseZ;
        }, 0);
    });

    quickAddEl.addEventListener('hidden.bs.modal', function() {
        quickAddEl.style.zIndex = '';
    });
})();

// ── Drag & Drop ──────────────────────────────
function csvDragOver(e) {
    e.preventDefault();
    document.getElementById('csvDropZone').style.borderColor = '#2563eb';
    document.getElementById('csvDropZone').style.background  = '#dbeafe';
}
function csvDragLeave(e) {
    document.getElementById('csvDropZone').style.borderColor = '#93c5fd';
    document.getElementById('csvDropZone').style.background  = '#f0f7ff';
}
function csvDrop(e) {
    e.preventDefault();
    csvDragLeave(e);
    const f = e.dataTransfer.files[0];
    if (f && f.name.toLowerCase().endsWith('.csv')) {
        const dt = new DataTransfer();
        dt.items.add(f);
        document.getElementById('purchaseCsvFile').files = dt.files;
        csvFileSelected(document.getElementById('purchaseCsvFile'));
    } else {
        _csvShowError('Only .csv files are accepted.');
    }
}

function csvFileSelected(input) {
    const f = input.files[0];
    if (!f) return;
    const sizeTxt = f.size > 1024*1024 ? (f.size/1024/1024).toFixed(1)+' MB' : (f.size/1024).toFixed(1)+' KB';

    document.getElementById('csvSelectedFileName').textContent = f.name;
    document.getElementById('csvSelectedFileSize').textContent = '(' + sizeTxt + ')';
    document.getElementById('csvSelectedFile').classList.remove('d-none');
    document.getElementById('csvDropZone').style.borderColor  = '#22c55e';
    document.getElementById('csvDropZone').style.background   = '#f0fdf4';
    document.getElementById('csvParseBtn').disabled           = false;
}

function csvClearFile() {
    document.getElementById('purchaseCsvFile').value = '';
    document.getElementById('csvSelectedFile').classList.add('d-none');
    document.getElementById('csvDropZone').style.borderColor = '#93c5fd';
    document.getElementById('csvDropZone').style.background  = '#f0f7ff';
    document.getElementById('csvParseBtn').disabled          = true;
}

// ── Step navigation ──────────────────────────
function _csvSetStep(n) {
    document.getElementById('csvStep1').classList.toggle('d-none', n !== 1);
    document.getElementById('csvStep2').classList.toggle('d-none', n !== 2);
    document.getElementById('csvParseBtn').classList.toggle('d-none', n !== 1);
    document.getElementById('csvConfirmBtn').classList.toggle('d-none', n !== 2);
    document.getElementById('csvBackBtn').style.display = n === 2 ? 'inline-block' : 'none';

    ['csvStep1Ind','csvStep2Ind','csvStep3Ind'].forEach((id, i) => {
        document.getElementById(id).classList.toggle('active', i < n);
    });
}

function csvGoToStep1() {
    _csvSetStep(1);
}

// ── Parse CSV ───────────────────────
async function submitCsvParse() {
    const fileInput = document.getElementById('purchaseCsvFile');
    if (!fileInput.files[0]) {
        _csvShowError('Pehle ek CSV file select karo.');
        return;
    }

    document.getElementById('csvParseProgress').classList.remove('d-none');
    document.getElementById('csvParseBtn').disabled = true;
    document.getElementById('csvParseBtn').innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Parsing...';

    try {
        await _csvFetchAndRender(fileInput.files[0]);
        document.getElementById('csvParseProgress').classList.add('d-none');
        document.getElementById('csvParseBtn').disabled = false;
        document.getElementById('csvParseBtn').innerHTML = '<i class="fas fa-search me-1"></i> Preview CSV';
        _csvSetStep(2);
    } catch (err) {
        document.getElementById('csvParseProgress').classList.add('d-none');
        document.getElementById('csvParseBtn').disabled = false;
        document.getElementById('csvParseBtn').innerHTML = '<i class="fas fa-search me-1"></i> Preview CSV';
        _csvShowError(err.message || 'Could not parse CSV.');
    }
}

// Re-parses the same CSV file and refreshes the preview table + missing-products
// list in place. Used after a missing product is created so the preview updates
// immediately without the user having to cancel and re-upload.
async function _csvRefreshPreviewSilently() {
    const fileInput = document.getElementById('purchaseCsvFile');
    if (!fileInput.files[0]) return; // nothing to re-parse against

    try {
        await _csvFetchAndRender(fileInput.files[0]);
    } catch (err) {
        // Silent refresh failing shouldn't interrupt the user — they can still
        // manually re-upload if needed.
        console.warn('CSV silent refresh failed:', err.message);
    }
}

// Shared fetch + state-sync + render logic for both the initial parse and
// the silent post-product-creation refresh.
async function _csvFetchAndRender(file) {
    const form = new FormData();
    form.append('csv_file', file);

    const resp = await fetch('/import/csv/', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        body: form
    });
    const data = await resp.json();

    if (!data.success) {
        throw new Error(data.error || 'Could not parse CSV.');
    }

    _csvParsedItems = data.items || [];
    _csvMissing     = data.missing_products || [];

    // entry.html's handleSaveProduct() decides whether "Save Medicine" should
    // call saveProductFromCsv() or saveQuickProduct() based on these two
    // globals. Keep them in sync so Save routes correctly for CSV-missing
    // products opened from this preview.
    if (typeof pendingCsvData !== 'undefined') pendingCsvData = data;
    if (typeof pendingMissingProducts !== 'undefined') pendingMissingProducts = _csvMissing;

    if (data.invoice_number) document.getElementById('csvInvoiceNumber').value = data.invoice_number;
    if (data.purchase_date)  document.getElementById('csvPurchaseDate').value  = data.purchase_date;

    if (_csvMissing.length) {
        let mpHtml = _csvMissing.map((mp, index) => `
            <span class="badge" style="background:#fef3c7;color:#92400e;border:1px solid #fde68a;margin:2px;padding:4px 8px;border-radius:6px;font-size:0.75rem;">
                <i class="fas fa-times-circle me-1 text-danger"></i>${mp.product} (Row ${mp.row})
                <button type="button" class="btn btn-link p-0 ms-1 text-primary" style="font-size:0.72rem;"
                    onclick="showProductCreationModal('${mp.product.replace(/'/g,"\\'")}')">
                    + Add
                </button>
            </span>`).join('');
        document.getElementById('csvMissingProductsList').innerHTML = mpHtml;
        document.getElementById('csvMissingProductsBar').classList.remove('d-none');
    } else {
        document.getElementById('csvMissingProductsBar').classList.add('d-none');
    }

    _csvRenderPreviewTable(_csvParsedItems);

    // If all products are missing (no matched items yet), disable Confirm & Load
    // so user is guided to add missing products via the + Add buttons above.
    const confirmBtn = document.getElementById('csvConfirmBtn');
    if (_csvParsedItems.length === 0 && _csvMissing.length > 0) {
        confirmBtn.disabled = true;
        confirmBtn.style.opacity = '0.55';
        confirmBtn.title = 'Pehle missing products add karo';
    } else {
        confirmBtn.disabled = false;
        confirmBtn.style.opacity = '';
        confirmBtn.title = '';
    }
}

// Whenever quickAddModal closes (Save or Cancel) WHILE csvImportModal is still
// open in the background, refresh its preview so newly created products show
// up immediately instead of needing a manual cancel + re-upload.
(function() {
    const quickAddEl = document.getElementById('quickAddModal');
    if (!quickAddEl) return;
    quickAddEl.addEventListener('hidden.bs.modal', function() {
        const csvModalEl = document.getElementById('csvImportModal');
        if (csvModalEl && csvModalEl.classList.contains('show')) {
            _csvRefreshPreviewSilently();
        }
    });
})();
function _csvRenderPreviewTable(items) {
    const tbody = document.getElementById('csvPreviewTbody');
    tbody.innerHTML = '';
    document.getElementById('csvItemCount').textContent = items.length;

    // Show empty-state row when all products are missing
    if (items.length === 0) {
        const emptyTr = document.createElement('tr');
        emptyTr.innerHTML = `
            <td colspan="11" style="text-align:center;padding:28px 16px;color:#9ca3af;font-size:0.85rem;">
                <i class="fas fa-box-open" style="font-size:1.8rem;display:block;margin-bottom:8px;opacity:0.4;"></i>
                Koi matched product nahi mila — upar missing products add karo
            </td>`;
        tbody.appendChild(emptyTr);
        return;
    }

    items.forEach((item, idx) => {
        const expiryDisplay = item.expiry_date ? String(item.expiry_date).substring(0, 7) : '';

        const tr = document.createElement('tr');
        tr.dataset.idx = idx;

        tr.innerHTML = `
            <td style="padding:6px 8px;color:#9ca3af;font-size:0.78rem;">${idx+1}</td>
            <td style="padding:4px 6px;">
                <input class="csv-editable fw-bold" style="min-width:160px;"
                    value="${_esc(item.name || '')}"
                    onchange="_csvUpdateItem(${idx},'name',this.value)">
                <div style="font-size:0.7rem;color:#9ca3af;">${_esc(item.packing||'')}</div>
            </td>
            <td style="padding:4px 6px;">
                <input class="csv-editable" style="max-width:100px;text-transform:uppercase;letter-spacing:.04em;"
                    value="${_esc(item.batch_number||'')}"
                    onchange="_csvUpdateItem(${idx},'batch_number',this.value)">
            </td>
            <td style="padding:4px 6px;">
                <input class="csv-editable" style="max-width:90px;"
                    placeholder="YYYY-MM-DD"
                    value="${_esc(expiryDisplay)}"
                    onchange="_csvUpdateItem(${idx},'expiry_date',this.value)">
            </td>
            <td style="padding:4px 6px;text-align:center;">
                <input class="csv-editable" type="number" min="0" style="max-width:60px;text-align:center;"
                    value="${item.quantity||0}"
                    onchange="_csvUpdateItem(${idx},'quantity',+this.value);_csvRecalcRow(${idx});_csvRefreshTotals()">
            </td>
            <td style="padding:4px 6px;text-align:center;color:#16a34a;">
                <input class="csv-editable" type="number" min="0" style="max-width:55px;text-align:center;"
                    value="${item.free_quantity||0}"
                    onchange="_csvUpdateItem(${idx},'free_quantity',+this.value);_csvRecalcRow(${idx});_csvRefreshTotals()">
            </td>
            <td style="padding:4px 6px;text-align:right;">
                <input class="csv-editable" type="number" min="0" step="0.01" style="max-width:85px;text-align:right;"
                    value="${(item.purchase_price||0).toFixed(2)}"
                    onchange="_csvUpdateItem(${idx},'purchase_price',+this.value);_csvRecalcRow(${idx});_csvRefreshTotals()">
            </td>
            <td style="padding:4px 6px;text-align:right;">
                <input class="csv-editable" type="number" min="0" step="0.01" style="max-width:80px;text-align:right;"
                    value="${(item.mrp||0).toFixed(2)}"
                    onchange="_csvUpdateItem(${idx},'mrp',+this.value);_csvRecalcRow(${idx});_csvRefreshTotals()">
            </td>
            <td style="padding:4px 6px;text-align:center;">
                <input class="csv-editable" type="number" min="0" step="0.01" style="max-width:55px;text-align:center;"
                    value="${(item.tax_percentage||0).toFixed(1)}"
                    onchange="_csvUpdateItem(${idx},'tax_percentage',+this.value);_csvRecalcRow(${idx});_csvRefreshTotals()">
            </td>
            <td style="padding:4px 6px;text-align:right;font-weight:700;color:#1d4ed8;" id="csvRowTotal${idx}">
                ₹${(item.total||0).toFixed(2)}
            </td>
            <td style="padding:4px 4px;">
                <button class="csv-remove-btn" onclick="_csvRemoveRow(${idx})" title="Remove">
                    <i class="fas fa-times"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    _csvRefreshTotals();
}

function _csvUpdateItem(idx, field, val) {
    if (_csvParsedItems[idx]) _csvParsedItems[idx][field] = val;
}

function _csvRecalcRow(idx) {
    const item = _csvParsedItems[idx];
    if (!item) return;

    const qty = Number(item.quantity) || 0;
    const price = Number(item.purchase_price) || 0;
    const taxPerc = Number(item.tax_percentage) || 0;

    const sub = qty * price;
    const tax = sub * taxPerc / 100;

    item.total = sub + tax;
    item.tax_amount = tax;

    const el = document.getElementById('csvRowTotal' + idx);
    if (el) el.textContent = '₹' + (item.total || 0).toFixed(2);

    _csvRefreshTotals();
}

function _csvRemoveRow(idx) {
    _csvParsedItems.splice(idx, 1);
    _csvRenderPreviewTable(_csvParsedItems);

    // Disable "Confirm & Load" if ALL products are missing — user must add them first
    const confirmBtn = document.getElementById('csvConfirmBtn');
    if (confirmBtn) {
        if (_csvParsedItems.length === 0 && _csvMissing.length > 0) {
            confirmBtn.disabled = true;
            confirmBtn.style.opacity = '0.55';
            confirmBtn.title = 'Pehle missing products add karo';
        } else {
            confirmBtn.disabled = false;
            confirmBtn.style.opacity = '';
            confirmBtn.title = '';
        }
    }
}

function csvClearAll() {
    if (!confirm('Remove all items?')) return;
    _csvParsedItems = [];
    _csvRenderPreviewTable([]);
}

function _csvRefreshTotals() {
    const totalQty = _csvParsedItems.reduce((s,i) => s + (i.quantity||0), 0);
    const totalAmt = _csvParsedItems.reduce((s,i) => s + (i.total||0), 0);
    document.getElementById('csvTotalQty').textContent = totalQty;
    document.getElementById('csvTotalAmount').textContent = '₹' + totalAmt.toFixed(2);
}

// ── Confirm & load into purchase form ────────
function csvConfirmAndLoad() {
    if (_csvParsedItems.length === 0) {
        alert('No items to load.');
        return;
    }

    const suppVal  = document.getElementById('csvSupplierSelect').value;
    const suppSearchInputVal = document.getElementById('csvSupplierSearchInput').value.trim();
    const invNum   = document.getElementById('csvInvoiceNumber').value.trim();
    const invDate  = document.getElementById('csvPurchaseDate').value;
    const payMode  = document.getElementById('csvPaymentMode').value;

    if (suppSearchInputVal && !suppVal) {
        showToast(`Supplier "${suppSearchInputVal}" does not exist. Please add this supplier first.`, 'error');
        return;
    }

    if (!suppVal || !invNum) {
        showToast('Please fill supplier and invoice number', 'error');
        return;
    }

    const mainSupplierSel = document.getElementById('supplierSelect');
    mainSupplierSel.value = suppVal;
    mainSupplierSel.dispatchEvent(new Event('change'));

    // Sync main page's supplierSearchInput
    const mainSupplierSI = document.getElementById('supplierSearchInput');
    if (mainSupplierSI && mainSupplierSel.selectedIndex >= 0) {
        const selOpt = mainSupplierSel.options[mainSupplierSel.selectedIndex];
        if (selOpt) mainSupplierSI.value = selOpt.text.split(' | ')[0];
    }

    document.getElementById('invoiceNumber').value = invNum;
    if (invDate) document.getElementById('purchaseDate').value = invDate;
    document.getElementById('summaryPaymentMode').value = payMode;

    items = [];
    _csvParsedItems.forEach(item => {
        item.quantity = Number(item.quantity) || 0;
        item.free_quantity = Number(item.free_quantity) || 0;
        item.purchase_price = Number(item.purchase_price) || 0;
        item.mrp = Number(item.mrp) || 0;
        item.tax_percentage = Number(item.tax_percentage) || 0;

        if (item.expiry_date && String(item.expiry_date).length === 7) {
            item.expiry_date = item.expiry_date + '-01';
        }

        if (!item.tax_amount) {
            const sub = item.quantity * item.purchase_price;
            item.tax_amount = sub * (item.tax_percentage / 100);
        }
        if (!item.total) {
            const sub = item.quantity * item.purchase_price;
            item.total = sub + (item.tax_amount || 0);
        }

        items.push(item);
    });

    renderTable();
    calculateSummary();

    bootstrap.Modal.getInstance(document.getElementById('csvImportModal')).hide();
    resetCsvImportModal();

    showToast(`${items.length} items loaded from CSV ✓`, 'success');
}

// ── Helpers ──────────────────────────────────
function _csvShowError(msg) {
    document.getElementById('csvParseErrorMsg').textContent = msg;
    document.getElementById('csvParseError').classList.remove('d-none');
}

function _esc(str) {
    return String(str||'')
        .replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function resetCsvImportModal() {
    if (isTransitioningToCsvSupplier) {
        isTransitioningToCsvSupplier = false;
        return;
    }
    _csvParsedItems  = [];
    _csvMissing      = [];
    csvClearFile();
    document.getElementById('csvImportWarnings').innerHTML   = '';
    document.getElementById('csvMissingProductsBar').classList.add('d-none');
    document.getElementById('csvPreviewTbody').innerHTML     = '';
    document.getElementById('csvParseError').classList.add('d-none');
    document.getElementById('csvParseProgress').classList.add('d-none');
    document.getElementById('csvInvoiceNumber').value        = '';
    document.getElementById('csvPurchaseDate').value         = '';
    document.getElementById('csvSupplierSelect').value       = '';
    document.getElementById('csvPaymentMode').value          = 'Cash';
    _csvSetStep(1);
}

document.getElementById('csvImportModal').addEventListener('hidden.bs.modal', resetCsvImportModal);

// Supplier Dropdown
(function() {
    const sel      = document.getElementById('csvSupplierSelect');
    const input    = document.getElementById('csvSupplierSearchInput');
    const dropdown = document.getElementById('csvSupplierDropdown');
    if (!sel || !input || !dropdown) return;

    let activeIdx = -1;
    let filtered  = [];

    function getOptions() {
        return Array.from(sel.options)
            .filter(o => o.value !== '')
            .map(o => ({ value: o.value, text: o.text }));
    }

    function renderDrop(opts) {
        filtered = [...opts];
        
        // Add a special "+ Add New" option
        const q = input.value.trim();
        const addNewOpt = { value: 'ADD_NEW', text: q ? `+ Add "${q}" as new supplier` : '+ Add New Supplier' };
        filtered.push(addNewOpt);
        
        activeIdx = filtered.length > 0 ? 0 : -1;
        dropdown.innerHTML = '';
        
        if (opts.length === 0 && q) {
            const noFoundDiv = document.createElement('div');
            noFoundDiv.style.cssText = 'padding:10px 14px;color:#888;font-size:0.85rem;';
            noFoundDiv.textContent = 'No suppliers found';
            dropdown.appendChild(noFoundDiv);
        }
        
        // Render options
        opts.forEach((opt, i) => {
            const div = document.createElement('div');
            div.style.cssText = 'padding:9px 14px;font-size:0.88rem;cursor:pointer;border-left:3px solid transparent;transition:all 0.15s;';
            div.textContent = opt.text;
            div.addEventListener('mouseover', () => { activeIdx = i; highlight(); });
            div.addEventListener('mousedown', e => { e.preventDefault(); pick(opt); });
            dropdown.appendChild(div);
        });
        
        // Render Add New Supplier option
        const addNewDiv = document.createElement('div');
        addNewDiv.style.cssText = 'padding:9px 14px;font-size:0.88rem;cursor:pointer;border-left:3px solid transparent;transition:all 0.15s;font-weight:bold;color:#1d4ed8;border-top:1px solid #e5e7eb;';
        addNewDiv.textContent = addNewOpt.text;
        const addNewIdx = opts.length;
        addNewDiv.addEventListener('mouseover', () => { activeIdx = addNewIdx; highlight(); });
        addNewDiv.addEventListener('mousedown', e => { e.preventDefault(); pick(addNewOpt); });
        dropdown.appendChild(addNewDiv);
        
        highlight();
        dropdown.style.display = 'block';
    }

    function highlight() {
        Array.from(dropdown.children).forEach((el, i) => {
            // Adjust index if we have "No suppliers found" placeholder in the DOM list
            const hasNoFoundPlaceholder = dropdown.firstChild && dropdown.firstChild.textContent === 'No suppliers found';
            const domIndex = hasNoFoundPlaceholder ? i - 1 : i;
            
            if (domIndex === -1) {
                el.style.background = '';
                el.style.color = '#888';
                return;
            }
            
            el.style.background   = domIndex === activeIdx ? 'linear-gradient(90deg,#6366f1,#818cf8)' : '';
            el.style.color        = domIndex === activeIdx ? '#fff' : '';
            el.style.borderLeftColor = domIndex === activeIdx ? '#4338ca' : 'transparent';
            if (domIndex === activeIdx) el.scrollIntoView({ block: 'nearest' });
        });
    }

    function pick(opt) {
        if (opt.value === 'ADD_NEW') {
            dropdown.style.display = 'none';
            activeIdx = -1;
            openCsvSupplierModal();
            return;
        }
        sel.value    = opt.value;
        input.value  = opt.text;
        dropdown.style.display = 'none';
        activeIdx = -1;
    }

    input.addEventListener('focus', () => {
        const q = input.value.trim().toLowerCase();
        renderDrop(q ? getOptions().filter(o => o.text.toLowerCase().includes(q)) : getOptions());
    });

    input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        if (!q) sel.value = '';
        renderDrop(q ? getOptions().filter(o => o.text.toLowerCase().includes(q)) : getOptions());
    });

    input.addEventListener('keydown', e => {
        if (dropdown.style.display === 'none') {
            if (e.key === 'ArrowDown') { e.preventDefault(); renderDrop(getOptions()); }
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault(); activeIdx = Math.min(activeIdx + 1, filtered.length - 1); highlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); highlight();
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            if (activeIdx >= 0 && filtered[activeIdx]) { e.preventDefault(); pick(filtered[activeIdx]); }
        } else if (e.key === 'Escape') {
            dropdown.style.display = 'none';
        }
    });

    document.addEventListener('mousedown', e => {
        const wrap = document.getElementById('csvSupplierSearchWrap');
        if (wrap && !wrap.contains(e.target)) dropdown.style.display = 'none';
    });

    const _origReset = resetCsvImportModal;
    window.resetCsvImportModal = function() {
        _origReset();
        input.value = '';
        sel.value   = '';
        dropdown.style.display = 'none';
    };
})();

// ── Supplier Modal helpers for CSV Import ──
function openCsvSupplierModal() {
    const csvImportModalEl = document.getElementById('csvImportModal');
    const csvSupplierModalEl = document.getElementById('csvSupplierModal');
    if (!csvImportModalEl || !csvSupplierModalEl) return;

    isTransitioningToCsvSupplier = true;
    const csvImportModal = bootstrap.Modal.getInstance(csvImportModalEl) || bootstrap.Modal.getOrCreateInstance(csvImportModalEl);
    csvImportModal.hide();

    const searchVal = document.getElementById('csvSupplierSearchInput').value.trim();
    document.getElementById('csvNewSupplierName').value = searchVal;

    document.getElementById('csvNewSupplierPhone').value = '';
    document.getElementById('csvNewSupplierAddress').value = '';
    document.getElementById('csvNewSupplierGst').value = '';
    document.getElementById('csvNewSupplierDl').value = '';

    const csvSupplierModal = bootstrap.Modal.getOrCreateInstance(csvSupplierModalEl);
    csvSupplierModal.show();
}

function closeCsvSupplierModal() {
    const csvSupplierModalEl = document.getElementById('csvSupplierModal');
    const csvImportModalEl = document.getElementById('csvImportModal');
    if (!csvSupplierModalEl || !csvImportModalEl) return;

    isTransitioningToCsvSupplier = true;
    const csvSupplierModal = bootstrap.Modal.getInstance(csvSupplierModalEl) || bootstrap.Modal.getOrCreateInstance(csvSupplierModalEl);
    csvSupplierModal.hide();

    const csvImportModal = bootstrap.Modal.getInstance(csvImportModalEl) || bootstrap.Modal.getOrCreateInstance(csvImportModalEl);
    csvImportModal.show();
}

async function saveCsvSupplier() {
    const url = '/type/drug-supplier/';
    const name = document.getElementById('csvNewSupplierName').value.trim();
    const phone = document.getElementById('csvNewSupplierPhone').value.trim();
    if (!name) return showToast('Supplier name is required', 'error');
    if (!phone) return showToast('Phone number is required', 'error');

    const payload = new URLSearchParams();
    payload.append('name', name);
    payload.append('phone', phone);
    payload.append('address', document.getElementById('csvNewSupplierAddress').value.trim());
    payload.append('gst_number', document.getElementById('csvNewSupplierGst').value.trim());
    payload.append('dl_number', document.getElementById('csvNewSupplierDl').value.trim());

    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: payload.toString()
        });
        const res = await resp.json();
        if (!res.success) {
            return showToast('Error: ' + (res.error || 'Could not save supplier'), 'error');
        }

        // Add to the CSV supplier select dropdown and input
        const sel = document.getElementById('csvSupplierSelect');
        const option = document.createElement('option');
        option.value = res.id;
        option.text = res.name;
        sel.appendChild(option);
        sel.value = res.id;

        // Set the search input value to show the new supplier's name
        const input = document.getElementById('csvSupplierSearchInput');
        if (input) input.value = res.name;

        // Also add it to the main page's supplierSelect so that it's in sync!
        const mainSel = document.getElementById('supplierSelect');
        if (mainSel) {
            const mainOpt = document.createElement('option');
            mainOpt.value = res.id;
            mainOpt.text = res.name;
            mainSel.appendChild(mainOpt);
        }

        closeCsvSupplierModal();
        showToast(`Supplier "${res.name}" added successfully`, 'success');
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}


// ════════════════════════════════════════════
//  Purchase AI OCR Logic
// ════════════════════════════════════════════

let _ocrParsedItems  = [];
let _ocrMissing      = [];
let ocrFilesList     = [];

function ocrDragOver(e) {
    e.preventDefault();
    const zone = document.getElementById('ocrDropZone');
    if (zone) {
        zone.style.borderColor = '#0f766e';
        zone.style.background = '#e6f4f1';
    }
}

function ocrDragLeave(e) {
    e.preventDefault();
    const zone = document.getElementById('ocrDropZone');
    if (zone) {
        zone.style.borderColor = '#0d9488';
        zone.style.background = '#f0fdf9';
    }
}

function ocrDrop(e) {
    e.preventDefault();
    ocrDragLeave(e);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        const fileInput = document.getElementById('purchaseBillFile');
        if (fileInput) {
            fileInput.files = files;
            ocrFileSelected(fileInput);
        }
    }
}

function ocrFileSelected(input) {
    const warningsContainer = document.getElementById('ocrImportWarnings');
    if (warningsContainer) warningsContainer.innerHTML = '';
    const errAlert = document.getElementById('ocrParseError');
    if (errAlert) errAlert.classList.add('d-none');

    if (input.files && input.files.length > 0) {
        for (let i = 0; i < input.files.length; i++) {
            ocrFilesList.push(input.files[i]);
        }
        input.value = ''; // Reset input to allow re-selecting same files
        renderOcrFilesList();
    }
}

function renderOcrFilesList() {
    const selectedFileContainer = document.getElementById('ocrSelectedFile');
    if (!selectedFileContainer) return;
    
    selectedFileContainer.innerHTML = '';
    
    if (ocrFilesList.length > 0) {
        selectedFileContainer.classList.remove('d-none');
        document.getElementById('ocrParseBtn').disabled = false;
        
        ocrFilesList.forEach((file, index) => {
            const fileItem = document.createElement('div');
            fileItem.style.background = '#f0fdf4';
            fileItem.style.border = '1px solid #bbf7d0';
            fileItem.style.borderRadius = '10px';
            fileItem.style.padding = '10px 16px';
            fileItem.style.marginBottom = '8px';
            fileItem.className = 'd-flex align-items-center justify-content-between';
            
            fileItem.innerHTML = `
                <div class="d-flex align-items-center gap-2">
                    <i class="fas fa-file-image" style="color:#16a34a;font-size:1.2rem;"></i>
                    <span class="fw-bold" style="color:#15803d;font-size:0.9rem;">Page ${index + 1}: ${file.name}</span>
                    <span class="text-muted" style="font-size:0.78rem;">(${(file.size / 1024).toFixed(1)} KB)</span>
                </div>
                <button type="button" class="btn btn-sm btn-outline-danger rounded-pill" onclick="ocrRemovePage(${index})" style="font-size:0.75rem;">
                    <i class="fas fa-times me-1"></i>Remove
                </button>
            `;
            selectedFileContainer.appendChild(fileItem);
        });
        
        const addMoreDiv = document.createElement('div');
        addMoreDiv.className = 'mt-3 text-center';
        addMoreDiv.innerHTML = `
            <button type="button" class="btn btn-sm btn-outline-teal rounded-pill px-3" style="color:#0d9488; border-color:#0d9488; font-size:0.8rem;" onclick="document.getElementById('purchaseBillFile').click()">
                <i class="fas fa-plus me-1"></i>+ Add Another Page
            </button>
        `;
        selectedFileContainer.appendChild(addMoreDiv);
    } else {
        selectedFileContainer.classList.add('d-none');
        document.getElementById('ocrParseBtn').disabled = true;
    }
}

function ocrRemovePage(index) {
    ocrFilesList.splice(index, 1);
    renderOcrFilesList();
}

window.ocrRemovePage = ocrRemovePage;

function ocrClearFile() {
    ocrFilesList = [];
    const fileInput = document.getElementById('purchaseBillFile');
    if (fileInput) fileInput.value = '';
    const cameraInput = document.getElementById('purchaseBillCamera');
    if (cameraInput) cameraInput.value = '';
    
    const selectedFileContainer = document.getElementById('ocrSelectedFile');
    if (selectedFileContainer) {
        selectedFileContainer.innerHTML = '';
        selectedFileContainer.classList.add('d-none');
    }
    document.getElementById('ocrParseBtn').disabled = true;
    document.getElementById('ocrParseError').classList.add('d-none');
}

function compressOcrImage(file, callback) {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = function(event) {
        const img = new Image();
        img.src = event.target.result;
        img.onload = function() {
            const maxDim = 1200;
            let width = img.width;
            let height = img.height;
            
            if (width > maxDim || height > maxDim) {
                if (width > height) {
                    height = Math.round((height * maxDim) / width);
                    width = maxDim;
                } else {
                    width = Math.round((width * maxDim) / height);
                    height = maxDim;
                }
            }
            
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, width, height);
            
            canvas.toBlob(function(blob) {
                callback(blob);
            }, 'image/jpeg', 0.85);
        };
    };
}

function submitOcrParse() {
    if (ocrFilesList.length === 0) return;

    const progress = document.getElementById('ocrParseProgress');
    const parseBtn = document.getElementById('ocrParseBtn');
    const ocrBackBtn = document.getElementById('ocrBackBtn');
    const cancelBtn = document.querySelector('#ocrImportModal .modal-footer .btn-outline-secondary');

    progress.classList.remove('d-none');
    parseBtn.disabled = true;
    if (ocrBackBtn) ocrBackBtn.disabled = true;
    if (cancelBtn) cancelBtn.disabled = true;
    
    document.getElementById('ocrParseError').classList.add('d-none');

    let compressedFilesCount = 0;
    const formData = new FormData();

    const onAllCompressed = () => {
        fetch('/import/ocr/', {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            progress.classList.add('d-none');
            parseBtn.disabled = false;
            if (ocrBackBtn) ocrBackBtn.disabled = false;
            if (cancelBtn) cancelBtn.disabled = false;

            if (data.success) {
                document.getElementById('ocrScansToday').textContent = data.scans_today;
                document.getElementById('ocrMaxScans').textContent = data.max_scans;

                document.getElementById('ocrInvoiceNumber').value = data.invoice_number || '';
                if (data.purchase_date) {
                    document.getElementById('ocrPurchaseDate').value = data.purchase_date;
                } else {
                    const today = new Date().toISOString().split('T')[0];
                    document.getElementById('ocrPurchaseDate').value = today;
                }
                if (data.payment_mode) {
                    document.getElementById('ocrPaymentMode').value = data.payment_mode;
                }

                const suppSelect = document.getElementById('ocrSupplierSelect');
                const suppSearchInput = document.getElementById('ocrSupplierSearchInput');
                if (data.supplier_id) {
                    suppSelect.value = data.supplier_id;
                    suppSelect.dispatchEvent(new Event('change'));
                    const opt = suppSelect.options[suppSelect.selectedIndex];
                    if (opt) suppSearchInput.value = opt.text;
                } else if (data.supplier_name) {
                    suppSearchInput.value = data.supplier_name;
                } else {
                    suppSearchInput.value = '';
                    suppSelect.value = '';
                }

                const dupWarning = document.getElementById('ocrDuplicateInvoiceWarning');
                if (data.is_duplicate) {
                    dupWarning.classList.remove('d-none');
                } else {
                    dupWarning.classList.add('d-none');
                }

                _ocrParsedItems = data.items || [];
                _ocrMissing = data.missing_products || [];

                _ocrRenderMissingBar();
                _ocrRenderPreviewTable(_ocrParsedItems);
                ocrGoToStep2();
            } else {
                _ocrShowError(data.error || 'Failed to scan the bill.');
            }
        })
        .catch(err => {
            progress.classList.add('d-none');
            parseBtn.disabled = false;
            if (ocrBackBtn) ocrBackBtn.disabled = false;
            if (cancelBtn) cancelBtn.disabled = false;
            _ocrShowError('Connection error: ' + err.message);
        });
    };

    ocrFilesList.forEach((file, idx) => {
        compressOcrImage(file, function(compressedBlob) {
            formData.append('bill_images', compressedBlob, `page_${idx + 1}.jpg`);
            compressedFilesCount++;
            
            const statusText = document.getElementById('ocrProgressStatusText');
            if (statusText) {
                statusText.textContent = `AI OCR engine is reading bill (Page ${compressedFilesCount} of ${ocrFilesList.length})...`;
            }
            
            if (compressedFilesCount === ocrFilesList.length) {
                onAllCompressed();
            }
        });
    });
}

function ocrGoToStep2() {
    document.getElementById('ocrStep1').classList.add('d-none');
    document.getElementById('ocrStep2').classList.remove('d-none');

    document.getElementById('ocrStep1Ind').classList.remove('active');
    document.getElementById('ocrStep2Ind').classList.add('active');

    document.getElementById('ocrParseBtn').classList.add('d-none');
    document.getElementById('ocrConfirmBtn').classList.remove('d-none');
    document.getElementById('ocrBackBtn').style.display = '';
}

function ocrGoToStep1() {
    document.getElementById('ocrStep2').classList.add('d-none');
    document.getElementById('ocrStep1').classList.remove('d-none');

    document.getElementById('ocrStep2Ind').classList.remove('active');
    document.getElementById('ocrStep1Ind').classList.add('active');

    document.getElementById('ocrConfirmBtn').classList.add('d-none');
    document.getElementById('ocrParseBtn').classList.remove('d-none');
    document.getElementById('ocrBackBtn').style.display = 'none';
}

function resetOcrImportModal() {
    if (isTransitioningToOcrSupplier) {
        isTransitioningToOcrSupplier = false;
        return;
    }
    ocrClearFile();
    ocrGoToStep1();
    _ocrParsedItems = [];
    _ocrMissing = [];
    document.getElementById('ocrSupplierSearchInput').value = '';
    document.getElementById('ocrSupplierSelect').value = '';
    document.getElementById('ocrInvoiceNumber').value = '';
    document.getElementById('ocrPurchaseDate').value = '';
    document.getElementById('ocrPaymentMode').value = 'Cash';
    document.getElementById('ocrPreviewTbody').innerHTML = '';
    document.getElementById('ocrTotalQty').textContent = '';
    document.getElementById('ocrTotalAmount').textContent = '';
    document.getElementById('ocrDuplicateInvoiceWarning').classList.add('d-none');
    document.getElementById('ocrMissingProductsBar').classList.add('d-none');
}

function _ocrShowError(msg) {
    document.getElementById('ocrParseErrorMsg').textContent = msg;
    document.getElementById('ocrParseError').classList.remove('d-none');
}

function _ocrRenderMissingBar() {
    const bar = document.getElementById('ocrMissingProductsBar');
    const list = document.getElementById('ocrMissingProductsList');
    if (_ocrMissing.length === 0) {
        bar.classList.add('d-none');
        list.innerHTML = '';
        return;
    }
    bar.classList.remove('d-none');
    let html = '<ul class="mb-2 ps-3">';
    _ocrMissing.forEach((p, idx) => {
        html += `<li><strong>Row ${p.row || (idx+1)}:</strong> "${_esc(p.product)}" (Batch: ${_esc(p.batch_number || 'N/A')}, Price: ₹${p.purchase_price || 0}, MRP: ₹${p.mrp || 0}) 
        <button class="btn btn-sm btn-link p-0 ms-2 fw-bold text-teal" style="font-size:0.75rem; text-decoration:none; color:#0d9488;" onclick="openOcrQuickAdd('${_esc(p.product)}')">
          <i class="fas fa-plus-circle"></i> Quick Add
        </button></li>`;
    });
    html += '</ul>';
    list.innerHTML = html;
}

window.openOcrQuickAdd = function(name) {
    const qaModalEl = document.getElementById('quickAddModal');
    if (!qaModalEl) return;
    const modal = bootstrap.Modal.getOrCreateInstance(qaModalEl);
    document.getElementById('quickName').value = name;
    modal.show();

    qaModalEl.addEventListener('hidden.bs.modal', async function onHide() {
        qaModalEl.removeEventListener('hidden.bs.modal', onHide);
        showToast('Rechecking database for matched products...', 'info');
        await _ocrRecheckMissingProducts();
    });
};

async function _ocrRecheckMissingProducts() {
    const stillMissing = [];
    for (const item of _ocrMissing) {
        try {
            const resp = await fetch(`/api/products/master-search/?q=${encodeURIComponent(item.product)}&nocache=1`);
            const data = await resp.json();
            if (data && data.length > 0) {
                const matchedProduct = data.find(p => (p.name || p.product_name || '').toLowerCase().trim() === item.product.toLowerCase().trim()) || data[0];
                const matchedName = matchedProduct.name || matchedProduct.product_name || '';
                _ocrParsedItems.push({
                    product_id: matchedProduct.id,
                    name: matchedName,
                    packing: matchedProduct.packing || matchedProduct.product_packing || '',
                    conversion_factor: matchedProduct.conversion_factor || 1,
                    batch_number: item.batch_number,
                    expiry_date: item.expiry_date,
                    quantity: item.quantity,
                    free_quantity: item.free_quantity,
                    total_units: (item.quantity + item.free_quantity) * (matchedProduct.conversion_factor || 1),
                    purchase_price: item.purchase_price,
                    tax_percentage: parseFloat(matchedProduct.tax_rate || 12.0),
                    tax_amount: (item.purchase_price * item.quantity) * parseFloat(matchedProduct.tax_rate || 12.0) / 100.0,
                    mrp: item.mrp,
                    sale_price: item.mrp,
                    total: item.total
                });
                showToast(`Matched "${matchedName}" successfully!`, 'success');
            } else {
                stillMissing.push(item);
            }
        } catch (e) {
            console.error(e);
            stillMissing.push(item);
        }
    }
    _ocrMissing = stillMissing;
    _ocrRenderMissingBar();
    _ocrRenderPreviewTable(_ocrParsedItems);
}

function _ocrRenderPreviewTable(items) {
    const tbody = document.getElementById('ocrPreviewTbody');
    tbody.innerHTML = '';

    if (items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11" class="text-center py-4 text-muted"><i class="fas fa-info-circle me-1"></i>No items to display. Upload a bill photo.</td></tr>`;
        return;
    }

    items.forEach((item, idx) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="text-muted" style="padding:6px;">${idx + 1}</td>
            <td><div class="fw-bold text-dark">${_esc(item.name)}</div></td>
            <td contenteditable="true" onblur="window._ocrUpdateItem(${idx}, 'batch_number', this.textContent)" style="background:#fffbeb; cursor:text;">${_esc(item.batch_number)}</td>
            <td contenteditable="true" onblur="window._ocrUpdateItem(${idx}, 'expiry_date', this.textContent)" style="background:#fffbeb; cursor:text;" placeholder="YYYY-MM-DD">${_esc(item.expiry_date || '')}</td>
            <td class="text-center" contenteditable="true" onblur="window._ocrUpdateItem(${idx}, 'quantity', this.textContent)" style="background:#fffbeb; cursor:text; font-weight:bold;">${item.quantity}</td>
            <td class="text-center text-success" contenteditable="true" onblur="window._ocrUpdateItem(${idx}, 'free_quantity', this.textContent)" style="background:#fffbeb; cursor:text;">${item.free_quantity}</td>
            <td class="text-end" contenteditable="true" onblur="window._ocrUpdateItem(${idx}, 'purchase_price', this.textContent)" style="background:#fffbeb; cursor:text;">${Number(item.purchase_price).toFixed(2)}</td>
            <td class="text-end" contenteditable="true" onblur="window._ocrUpdateItem(${idx}, 'mrp', this.textContent)" style="background:#fffbeb; cursor:text;">${Number(item.mrp).toFixed(2)}</td>
            <td class="text-center" contenteditable="true" onblur="window._ocrUpdateItem(${idx}, 'tax_percentage', this.textContent)" style="background:#fffbeb; cursor:text;">${item.tax_percentage}</td>
            <td class="text-end fw-bold text-teal" id="ocrRowTotal-${idx}">₹${Number(item.total).toFixed(2)}</td>
            <td class="text-center">
                <button type="button" class="btn btn-sm btn-link text-danger p-0" onclick="window._ocrRemoveRow(${idx})" title="Remove item">
                    <i class="fas fa-trash-alt"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    _ocrRefreshTotals();
}

function _ocrUpdateItem(idx, field, value) {
    const item = _ocrParsedItems[idx];
    if (!item) return;

    if (field === 'quantity' || field === 'free_quantity') {
        item[field] = parseInt(value) || 0;
    } else if (field === 'purchase_price' || field === 'mrp' || field === 'tax_percentage') {
        item[field] = parseFloat(value) || 0.0;
    } else {
        item[field] = value.trim();
    }

    _ocrRecalcRow(idx);
    _ocrRefreshTotals();
}

function _ocrRecalcRow(idx) {
    const item = _ocrParsedItems[idx];
    if (!item) return;

    const qty = item.quantity || 0;
    const price = item.purchase_price || 0.0;
    const taxRate = item.tax_percentage || 0.0;

    const taxAmt = (price * qty) * (taxRate / 100.0);
    item.tax_amount = taxAmt;
    item.total = (price * qty) + taxAmt;

    const cell = document.getElementById(`ocrRowTotal-${idx}`);
    if (cell) {
        cell.textContent = '₹' + item.total.toFixed(2);
    }
}

function _ocrRefreshTotals() {
    const totalQty = _ocrParsedItems.reduce((s, i) => s + (i.quantity || 0), 0);
    const totalAmt = _ocrParsedItems.reduce((s, i) => s + (i.total || 0), 0);
    const totalQtyEl = document.getElementById('ocrTotalQty');
    if (totalQtyEl) totalQtyEl.textContent = totalQty;
    const totalAmtEl = document.getElementById('ocrTotalAmount');
    if (totalAmtEl) totalAmtEl.textContent = '₹' + totalAmt.toFixed(2);

    const confirmBtn = document.getElementById('ocrConfirmBtn');
    if (confirmBtn) {
        if (_ocrParsedItems.length === 0) {
            confirmBtn.disabled = true;
            confirmBtn.style.opacity = '0.55';
        } else {
            confirmBtn.disabled = false;
            confirmBtn.style.opacity = '';
        }
    }
}

function _ocrRemoveRow(idx) {
    if (!confirm('Remove this item?')) return;
    _ocrParsedItems.splice(idx, 1);
    _ocrRenderPreviewTable(_ocrParsedItems);
}

function ocrClearAll() {
    if (!confirm('Remove all items?')) return;
    _ocrParsedItems = [];
    _ocrRenderPreviewTable([]);
}

function ocrConfirmAndLoad() {
    if (_ocrParsedItems.length === 0) {
        alert('No items to load.');
        return;
    }

    const suppVal = document.getElementById('ocrSupplierSelect').value;
    const suppSearchInputVal = document.getElementById('ocrSupplierSearchInput').value.trim();
    const invNum = document.getElementById('ocrInvoiceNumber').value.trim();
    const invDate = document.getElementById('ocrPurchaseDate').value;
    const payMode = document.getElementById('ocrPaymentMode').value;

    if (suppSearchInputVal && !suppVal) {
        showToast(`Supplier "${suppSearchInputVal}" does not exist. Please add this supplier first.`, 'error');
        return;
    }

    if (!suppVal || !invNum) {
        showToast('Please select supplier and enter invoice number', 'error');
        return;
    }

    const mainSupplierSel = document.getElementById('supplierSelect');
    mainSupplierSel.value = suppVal;
    mainSupplierSel.dispatchEvent(new Event('change'));

    const mainSupplierSI = document.getElementById('supplierSearchInput');
    if (mainSupplierSI && mainSupplierSel.selectedIndex >= 0) {
        const selOpt = mainSupplierSel.options[mainSupplierSel.selectedIndex];
        if (selOpt) mainSupplierSI.value = selOpt.text.split(' | ')[0];
    }

    document.getElementById('invoiceNumber').value = invNum;
    if (invDate) document.getElementById('purchaseDate').value = invDate;
    document.getElementById('summaryPaymentMode').value = payMode;

    items = [];
    _ocrParsedItems.forEach(item => {
        item.quantity = Number(item.quantity) || 0;
        item.free_quantity = Number(item.free_quantity) || 0;
        item.purchase_price = Number(item.purchase_price) || 0;
        item.mrp = Number(item.mrp) || 0;
        item.tax_percentage = Number(item.tax_percentage) || 0;

        if (item.expiry_date && String(item.expiry_date).length === 7) {
            item.expiry_date = item.expiry_date + '-01';
        }

        if (!item.tax_amount) {
            const sub = item.quantity * item.purchase_price;
            item.tax_amount = sub * (item.tax_percentage / 100);
        }
        if (!item.total) {
            const sub = item.quantity * item.purchase_price;
            item.total = sub + (item.tax_amount || 0);
        }

        items.push(item);
    });

    renderTable();
    calculateSummary();

    const ocrModalEl = document.getElementById('ocrImportModal');
    if (ocrModalEl) {
        bootstrap.Modal.getInstance(ocrModalEl).hide();
    }
    resetOcrImportModal();

    showToast(`${items.length} items loaded from AI OCR Scan ✓`, 'success');
}

// ── Supplier Dropdown Autocomplete for OCR ──
(function() {
    const sel      = document.getElementById('ocrSupplierSelect');
    const input    = document.getElementById('ocrSupplierSearchInput');
    const dropdown = document.getElementById('ocrSupplierDropdown');
    if (!sel || !input || !dropdown) return;

    let activeIdx = -1;
    let filtered  = [];

    function getOptions() {
        return Array.from(sel.options)
            .filter(o => o.value !== '')
            .map(o => ({ value: o.value, text: o.text }));
    }

    function renderDrop(opts) {
        filtered = [...opts];
        const q = input.value.trim();
        const addNewOpt = { value: 'ADD_NEW', text: q ? `+ Add "${q}" as new supplier` : '+ Add New Supplier' };
        filtered.push(addNewOpt);
        activeIdx = filtered.length > 0 ? 0 : -1;
        dropdown.innerHTML = '';
        if (opts.length === 0 && q) {
            const noFoundDiv = document.createElement('div');
            noFoundDiv.style.cssText = 'padding:10px 14px;color:#888;font-size:0.85rem;';
            noFoundDiv.textContent = 'No suppliers found';
            dropdown.appendChild(noFoundDiv);
        }
        opts.forEach((opt, i) => {
            const div = document.createElement('div');
            div.style.cssText = 'padding:9px 14px;font-size:0.88rem;cursor:pointer;border-left:3px solid transparent;transition:all 0.15s;';
            div.textContent = opt.text;
            div.addEventListener('mouseover', () => { activeIdx = i; highlight(); });
            div.addEventListener('mousedown', e => { e.preventDefault(); pick(opt); });
            dropdown.appendChild(div);
        });
        const addNewDiv = document.createElement('div');
        addNewDiv.style.cssText = 'padding:9px 14px;font-size:0.88rem;cursor:pointer;border-left:3px solid transparent;transition:all 0.15s;font-weight:bold;color:#0d9488;border-top:1px solid #e5e7eb;';
        addNewDiv.textContent = addNewOpt.text;
        const addNewIdx = opts.length;
        addNewDiv.addEventListener('mouseover', () => { activeIdx = addNewIdx; highlight(); });
        addNewDiv.addEventListener('mousedown', e => { e.preventDefault(); pick(addNewOpt); });
        dropdown.appendChild(addNewDiv);
        highlight();
        dropdown.style.display = 'block';
    }

    function highlight() {
        Array.from(dropdown.children).forEach((el, i) => {
            const hasNoFoundPlaceholder = dropdown.firstChild && dropdown.firstChild.textContent === 'No suppliers found';
            const domIndex = hasNoFoundPlaceholder ? i - 1 : i;
            if (domIndex === -1) {
                el.style.background = '';
                el.style.color = '#888';
                return;
            }
            el.style.background   = domIndex === activeIdx ? 'linear-gradient(90deg,#0d9488,#0f766e)' : '';
            el.style.color        = domIndex === activeIdx ? '#fff' : '';
            el.style.borderLeftColor = domIndex === activeIdx ? '#0f766e' : 'transparent';
            if (domIndex === activeIdx) el.scrollIntoView({ block: 'nearest' });
        });
    }

    function pick(opt) {
        if (opt.value === 'ADD_NEW') {
            dropdown.style.display = 'none';
            activeIdx = -1;
            openOcrSupplierModal();
            return;
        }
        sel.value    = opt.value;
        input.value  = opt.text;
        dropdown.style.display = 'none';
        activeIdx = -1;
    }

    input.addEventListener('focus', () => {
        const q = input.value.trim().toLowerCase();
        renderDrop(q ? getOptions().filter(o => o.text.toLowerCase().includes(q)) : getOptions());
    });

    input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        if (!q) sel.value = '';
        renderDrop(q ? getOptions().filter(o => o.text.toLowerCase().includes(q)) : getOptions());
    });

    input.addEventListener('keydown', e => {
        if (dropdown.style.display === 'none') {
            if (e.key === 'ArrowDown') { e.preventDefault(); renderDrop(getOptions()); }
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault(); activeIdx = Math.min(activeIdx + 1, filtered.length - 1); highlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); highlight();
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            if (activeIdx >= 0 && filtered[activeIdx]) { e.preventDefault(); pick(filtered[activeIdx]); }
        } else if (e.key === 'Escape') {
            dropdown.style.display = 'none';
        }
    });

    document.addEventListener('mousedown', e => {
        const wrap = document.getElementById('ocrSupplierSearchWrap');
        if (wrap && !wrap.contains(e.target)) dropdown.style.display = 'none';
    });

    const _origOcrReset = resetOcrImportModal;
    window.resetOcrImportModal = function() {
        _origOcrReset();
        input.value = '';
        sel.value   = '';
        dropdown.style.display = 'none';
    };
})();

// Supplier Modal helper functions for OCR
function openOcrSupplierModal() {
    const ocrImportModalEl = document.getElementById('ocrImportModal');
    const ocrSupplierModalEl = document.getElementById('ocrSupplierModal');
    if (!ocrImportModalEl || !ocrSupplierModalEl) return;

    isTransitioningToOcrSupplier = true;
    bootstrap.Modal.getOrCreateInstance(ocrImportModalEl).hide();

    const searchVal = document.getElementById('ocrSupplierSearchInput').value.trim();
    document.getElementById('ocrNewSupplierName').value = searchVal;
    document.getElementById('ocrNewSupplierPhone').value = '';
    document.getElementById('ocrNewSupplierAddress').value = '';
    document.getElementById('ocrNewSupplierGst').value = '';
    document.getElementById('ocrNewSupplierDl').value = '';

    bootstrap.Modal.getOrCreateInstance(ocrSupplierModalEl).show();
}

function closeOcrSupplierModal() {
    const ocrSupplierModalEl = document.getElementById('ocrSupplierModal');
    const ocrImportModalEl = document.getElementById('ocrImportModal');
    if (!ocrSupplierModalEl || !ocrImportModalEl) return;

    isTransitioningToOcrSupplier = true;
    bootstrap.Modal.getOrCreateInstance(ocrSupplierModalEl).hide();
    bootstrap.Modal.getOrCreateInstance(ocrImportModalEl).show();
}

async function saveOcrSupplier() {
    const url = '/type/drug-supplier/';
    const name = document.getElementById('ocrNewSupplierName').value.trim();
    const phone = document.getElementById('ocrNewSupplierPhone').value.trim();
    if (!name) return showToast('Supplier name is required', 'error');
    if (!phone) return showToast('Phone number is required', 'error');

    const payload = new URLSearchParams();
    payload.append('name', name);
    payload.append('phone', phone);
    payload.append('address', document.getElementById('ocrNewSupplierAddress').value.trim());
    payload.append('gst_number', document.getElementById('ocrNewSupplierGst').value.trim());
    payload.append('dl_number', document.getElementById('ocrNewSupplierDl').value.trim());

    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: payload.toString()
        });
        const res = await resp.json();
        if (!res.success) {
            return showToast('Error: ' + (res.error || 'Could not save supplier'), 'error');
        }

        const sel = document.getElementById('ocrSupplierSelect');
        const option = document.createElement('option');
        option.value = res.id;
        option.text = res.name;
        sel.appendChild(option);
        sel.value = res.id;

        const input = document.getElementById('ocrSupplierSearchInput');
        if (input) input.value = res.name;

        const mainSel = document.getElementById('supplierSelect');
        if (mainSel) {
            const mainOpt = document.createElement('option');
            mainOpt.value = res.id;
            mainOpt.text = res.name;
            mainSel.appendChild(mainOpt);
        }

        closeOcrSupplierModal();
        showToast(`Supplier "${res.name}" added successfully`, 'success');
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

const ocrImportModalEl = document.getElementById('ocrImportModal');
if (ocrImportModalEl) {
    ocrImportModalEl.addEventListener('hidden.bs.modal', resetOcrImportModal);
}

// ── Expose functions called from inline HTML onclick/onchange ───────────
window.csvDragOver             = csvDragOver;
window.csvDragLeave            = csvDragLeave;
window.csvDrop                 = csvDrop;
window.csvFileSelected         = csvFileSelected;
window.csvClearFile            = csvClearFile;
window.csvGoToStep1            = csvGoToStep1;
window.submitCsvParse          = submitCsvParse;
window.csvConfirmAndLoad       = csvConfirmAndLoad;
window.csvClearAll             = csvClearAll;
window._csvUpdateItem          = _csvUpdateItem;
window._csvRecalcRow           = _csvRecalcRow;
window._csvRefreshTotals       = _csvRefreshTotals;
window._csvRemoveRow           = _csvRemoveRow;
window.openCsvSupplierModal    = openCsvSupplierModal;
window.closeCsvSupplierModal   = closeCsvSupplierModal;
window.saveCsvSupplier         = saveCsvSupplier;

window.ocrDragOver             = ocrDragOver;
window.ocrDragLeave            = ocrDragLeave;
window.ocrDrop                 = ocrDrop;
window.ocrFileSelected         = ocrFileSelected;
window.ocrClearFile            = ocrClearFile;
window.ocrGoToStep1            = ocrGoToStep1;
window.submitOcrParse          = submitOcrParse;
window.ocrConfirmAndLoad       = ocrConfirmAndLoad;
window.ocrClearAll             = ocrClearAll;
window._ocrUpdateItem          = _ocrUpdateItem;
window._ocrRecalcRow           = _ocrRecalcRow;
window._ocrRefreshTotals       = _ocrRefreshTotals;
window._ocrRemoveRow           = _ocrRemoveRow;
window.openOcrSupplierModal    = openOcrSupplierModal;
window.closeOcrSupplierModal   = closeOcrSupplierModal;
window.saveOcrSupplier         = saveOcrSupplier;

})(); // ← closes the top-level IIFE opened at the start of this file