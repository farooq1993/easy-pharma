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

console.log("✅ CSV Import JS Loaded");

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
    const invNum   = document.getElementById('csvInvoiceNumber').value.trim();
    const invDate  = document.getElementById('csvPurchaseDate').value;
    const payMode  = document.getElementById('csvPaymentMode').value;

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

// Ensure backdrop stacking is also handled cleanly for csvSupplierModal just in case
(function() {
    const csvSuppEl = document.getElementById('csvSupplierModal');
    if (!csvSuppEl) return;

    csvSuppEl.addEventListener('show.bs.modal', function() {
        const openBackdrops = document.querySelectorAll('.modal-backdrop').length;
        const baseZ = 1060 + (openBackdrops * 20);
        csvSuppEl.style.zIndex = baseZ + 10;
        setTimeout(() => {
            const backdrops = document.querySelectorAll('.modal-backdrop');
            const thisBackdrop = backdrops[backdrops.length - 1];
            if (thisBackdrop) thisBackdrop.style.zIndex = baseZ;
        }, 0);
    });

    csvSuppEl.addEventListener('hidden.bs.modal', function() {
        csvSuppEl.style.zIndex = '';
    });
})();

function closeCsvSupplierModal() {
    const csvSupplierModalEl = document.getElementById('csvSupplierModal');
    const csvImportModalEl = document.getElementById('csvImportModal');
    if (!csvSupplierModalEl || !csvImportModalEl) return;

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
// Note: window.resetCsvImportModal is already set above (wrapped version
// that also clears the supplier search input) — don't overwrite it here.

})(); // ← closes the top-level IIFE opened at the start of this file