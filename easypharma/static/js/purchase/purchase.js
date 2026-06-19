// ════════════════════════════════════════════
//  Purchase CSV Import Logic
// ════════════════════════════════════════════

let _csvParsedItems  = [];   // items from backend
let _csvMissing      = [];   // missing products from backend

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
    const sizeTxt = f.size > 1024*1024
        ? (f.size/1024/1024).toFixed(1)+' MB'
        : (f.size/1024).toFixed(1)+' KB';

    document.getElementById('csvSelectedFileName').textContent = f.name;
    document.getElementById('csvSelectedFileSize').textContent = '(' + sizeTxt + ')';
    document.getElementById('csvSelectedFile').classList.remove('d-none');
    document.getElementById('csvDropZone').style.borderColor  = '#22c55e';
    document.getElementById('csvDropZone').style.background   = '#f0fdf4';
    document.getElementById('csvParseBtn').disabled           = false;
    document.getElementById('csvParseError').classList.add('d-none');
}

function csvClearFile() {
    document.getElementById('purchaseCsvFile').value = '';
    document.getElementById('csvSelectedFile').classList.add('d-none');
    document.getElementById('csvDropZone').style.borderColor = '#93c5fd';
    document.getElementById('csvDropZone').style.background  = '#f0f7ff';
    document.getElementById('csvParseBtn').disabled          = true;
    document.getElementById('csvParseError').classList.add('d-none');
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

// ── Parse (Step 1 → 2) ───────────────────────
async function submitCsvParse() {
    const fileInput = document.getElementById('purchaseCsvFile');
    if (!fileInput.files[0]) {
        _csvShowError('Pehle ek CSV file select karo.');
        return;
    }

    // Show loader
    document.getElementById('csvParseProgress').classList.remove('d-none');
    document.getElementById('csvParseError').classList.add('d-none');
    document.getElementById('csvParseBtn').disabled = true;
    document.getElementById('csvParseBtn').innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Parsing...';

    const form = new FormData();
    form.append('csv_file', fileInput.files[0]);

    try {
        const resp = await fetch('/import/csv/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            body: form
        });
        const data = await resp.json();

        document.getElementById('csvParseProgress').classList.add('d-none');
        document.getElementById('csvParseBtn').disabled = false;
        document.getElementById('csvParseBtn').innerHTML = '<i class="fas fa-search me-1"></i> Preview CSV';

        if (!data.success) {
            _csvShowError(data.error || 'Could not parse CSV.');
            return;
        }

        // Store data
        _csvParsedItems = data.items || [];
        _csvMissing     = data.missing_products || [];

        // Pre-fill invoice meta
        if (data.invoice_number) document.getElementById('csvInvoiceNumber').value = data.invoice_number;
        if (data.purchase_date)  document.getElementById('csvPurchaseDate').value  = data.purchase_date;

        // Supplier auto-select by name — update both hidden select + search input
        if (data.supplier_name) {
            const sel = document.getElementById('csvSupplierSelect');
            const match = Array.from(sel.options).find(o =>
                o.text.toLowerCase().includes(data.supplier_name.toLowerCase())
            );
            if (match) {
                sel.value = match.value;
                const si = document.getElementById('csvSupplierSearchInput');
                if (si) si.value = match.text;
            }
        }

        // Handle missing products
        if (_csvMissing.length) {
            let mpHtml = _csvMissing.map(mp =>
                `<span class="badge" style="background:#fef3c7;color:#92400e;border:1px solid #fde68a;margin:2px;padding:4px 8px;border-radius:6px;font-size:0.75rem;">
                    <i class="fas fa-times-circle me-1 text-danger"></i>${mp.product} (Row ${mp.row})
                    <button type="button" class="btn btn-link p-0 ms-1 text-primary" style="font-size:0.72rem;vertical-align:middle;"
                        onclick="bootstrap.Modal.getInstance(document.getElementById('csvImportModal')).hide();setTimeout(()=>showProductCreationModal('${mp.product.replace(/'/g,"\\'")}'),300);">
                        + Add
                    </button>
                </span>`
            ).join('');
            document.getElementById('csvMissingProductsList').innerHTML = mpHtml;
            document.getElementById('csvMissingProductsBar').classList.remove('d-none');
        } else {
            document.getElementById('csvMissingProductsBar').classList.add('d-none');
        }

        if (_csvParsedItems.length === 0 && _csvMissing.length > 0) {
            _csvShowError('No products found in system. Please create them first, then re-upload the CSV.');
            return;
        }
        if (_csvParsedItems.length === 0) {
            _csvShowError('No valid data found in CSV.');
            return;
        }

        _csvRenderPreviewTable(_csvParsedItems);
        _csvSetStep(2);

    } catch (err) {
        document.getElementById('csvParseProgress').classList.add('d-none');
        document.getElementById('csvParseBtn').disabled = false;
        document.getElementById('csvParseBtn').innerHTML = '<i class="fas fa-search me-1"></i> Preview CSV';
        _csvShowError('Network error: ' + err.message);
    }
}

// ── Render editable preview table ────────────
function _csvRenderPreviewTable(items) {
    const tbody = document.getElementById('csvPreviewTbody');
    tbody.innerHTML = '';
    document.getElementById('csvItemCount').textContent = items.length;

    items.forEach((item, idx) => {
        const expiryDisplay = item.expiry_date
            ? String(item.expiry_date).substring(0, 7)   // YYYY-MM
            : '';

        const tr = document.createElement('tr');
        if (item._missing) tr.className = 'csv-row-missing';
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
                    placeholder="MM/YYYY"
                    value="${_esc(expiryDisplay)}"
                    onchange="_csvUpdateItem(${idx},'expiry_date',this.value)">
            </td>
            <td style="padding:4px 6px;text-align:center;">
                <input class="csv-editable" type="number" min="0" style="max-width:60px;text-align:center;"
                    value="${item.quantity||0}"
                    onchange="_csvUpdateItem(${idx},'quantity',+this.value);_csvRefreshTotals()">
            </td>
            <td style="padding:4px 6px;text-align:center;color:#16a34a;">
                <input class="csv-editable" type="number" min="0" style="max-width:55px;text-align:center;"
                    value="${item.free_quantity||0}"
                    onchange="_csvUpdateItem(${idx},'free_quantity',+this.value)">
            </td>
            <td style="padding:4px 6px;text-align:right;">
                <input class="csv-editable" type="number" min="0" step="0.01" style="max-width:85px;text-align:right;"
                    value="${(item.purchase_price||0).toFixed(2)}"
                    onchange="_csvUpdateItem(${idx},'purchase_price',+this.value);_csvRecalcRow(${idx})">
            </td>
            <td style="padding:4px 6px;text-align:right;">
                <input class="csv-editable" type="number" min="0" step="0.01" style="max-width:80px;text-align:right;"
                    value="${(item.mrp||0).toFixed(2)}"
                    onchange="_csvUpdateItem(${idx},'mrp',+this.value)">
            </td>
            <td style="padding:4px 6px;text-align:center;">
                <input class="csv-editable" type="number" min="0" step="0.01" style="max-width:55px;text-align:center;"
                    value="${(item.tax_percentage||0).toFixed(1)}"
                    onchange="_csvUpdateItem(${idx},'tax_percentage',+this.value);_csvRecalcRow(${idx})">
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
    const sub = (item.quantity||0) * (item.purchase_price||0);
    const tax = sub * (item.tax_percentage||0) / 100;
    item.total = sub + tax;
    item.tax_amount = tax;
    const el = document.getElementById('csvRowTotal'+idx);
    if (el) el.textContent = '₹' + item.total.toFixed(2);
    _csvRefreshTotals();
}

function _csvRemoveRow(idx) {
    _csvParsedItems.splice(idx, 1);
    _csvRenderPreviewTable(_csvParsedItems);
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
// ── Confirm & load into purchase form ────────
function csvConfirmAndLoad() {
    if (_csvParsedItems.length === 0) {
        alert('No items to load.');
        return;
    }

    // Validate invoice meta
    const suppVal  = document.getElementById('csvSupplierSelect').value;
    const invNum   = document.getElementById('csvInvoiceNumber').value.trim();
    const invDate  = document.getElementById('csvPurchaseDate').value;
    const payMode  = document.getElementById('csvPaymentMode').value;

    if (!suppVal) {
        document.getElementById('csvSupplierSearchInput').focus();
        showToast('Please select a supplier', 'error');
        return;
    }
    if (!invNum) {
        document.getElementById('csvInvoiceNumber').focus();
        showToast('Please enter invoice number', 'error');
        return;
    }

    // ── Fill main purchase form ──────────────
    const mainSupplierSel = document.getElementById('supplierSelect');
    mainSupplierSel.value = suppVal;
    mainSupplierSel.dispatchEvent(new Event('change'));

    const suppSearchInput = document.getElementById('supplierSearchInput');
    if (suppSearchInput) {
        const selOpt = mainSupplierSel.options[mainSupplierSel.selectedIndex];
        if (selOpt) suppSearchInput.value = selOpt.text.split(' | ')[0];
    }

    document.getElementById('invoiceNumber').value = invNum;
    if (invDate) document.getElementById('purchaseDate').value = invDate;
    document.getElementById('summaryPaymentMode').value = payMode;

    // 3. Load items with proper cleaning
    items = [];   // Reset global items array

    _csvParsedItems.forEach(item => {
        // Clean expiry_date
        if (item.expiry_date) {
            let ed = String(item.expiry_date).trim();
            if (ed.length === 7 && ed.includes('-')) {
                item.expiry_date = ed + '-01';
            } else if (ed.length === 10) {
                // good
            } else if (/^\d{2}\/\d{4}$/.test(ed)) {
                const [mm, yyyy] = ed.split('/');
                item.expiry_date = `${yyyy}-${mm}-01`;
            } else {
                item.expiry_date = ed + '-01';
            }
        } else {
            item.expiry_date = null;
        }

        // Clean numbers
        item.quantity = Number(item.quantity) || 0;
        item.free_quantity = Number(item.free_quantity) || 0;
        item.purchase_price = Number(item.purchase_price) || 0;
        item.mrp = Number(item.mrp) || 0;
        item.tax_percentage = Number(item.tax_percentage) || 0;

        // Calculate missing fields
        if (!item.tax_amount) {
            const sub = item.quantity * item.purchase_price;
            item.tax_amount = sub * (item.tax_percentage / 100);
        }
        if (!item.total) {
            const sub = item.quantity * item.purchase_price;
            item.total = sub + (item.tax_amount || 0);
        }
        if (!item.total_units) {
            item.total_units = (item.quantity + item.free_quantity) * (item.conversion_factor || 1);
        }
        if (!item.sale_price || item.sale_price === 0) {
            item.sale_price = item.mrp || item.purchase_price;
        }

        items.push(item);
    });

    // 4. Render & Save
    renderTable();
    calculateSummary();

    // 5. Close modal
    bootstrap.Modal.getInstance(document.getElementById('csvImportModal')).hide();
    resetCsvImportModal();

    showToast(`${_csvParsedItems.length} items loaded from CSV ✓`, 'success');

    setTimeout(() => {
        const tableEl = document.getElementById('purchaseTable');
        if (tableEl) tableEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 300);
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

// Reset when modal closes via backdrop/X
document.getElementById('csvImportModal').addEventListener('hidden.bs.modal', resetCsvImportModal);

// ── Searchable Supplier Dropdown (CSV modal) ──
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
        filtered  = opts;
        activeIdx = opts.length > 0 ? 0 : -1;
        dropdown.innerHTML = '';
        if (opts.length === 0) {
            dropdown.innerHTML = '<div style="padding:10px 14px;color:#888;font-size:0.85rem;">No suppliers found</div>';
        } else {
            opts.forEach((opt, i) => {
                const div = document.createElement('div');
                div.style.cssText = 'padding:9px 14px;font-size:0.88rem;cursor:pointer;border-left:3px solid transparent;transition:all 0.15s;';
                div.textContent = opt.text;
                div.addEventListener('mouseover', () => { activeIdx = i; highlight(); });
                div.addEventListener('mousedown', e => { e.preventDefault(); pick(opt); });
                dropdown.appendChild(div);
            });
        }
        highlight();
        dropdown.style.display = 'block';
    }

    function highlight() {
        Array.from(dropdown.children).forEach((el, i) => {
            el.style.background   = i === activeIdx ? 'linear-gradient(90deg,#6366f1,#818cf8)' : '';
            el.style.color        = i === activeIdx ? '#fff' : '';
            el.style.borderLeftColor = i === activeIdx ? '#4338ca' : 'transparent';
            if (i === activeIdx) el.scrollIntoView({ block: 'nearest' });
        });
    }

    function pick(opt) {
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

    // Clear search input on modal reset
    const _origReset = resetCsvImportModal;
    window.resetCsvImportModal = function() {
        _origReset();
        input.value = '';
        sel.value   = '';
        dropdown.style.display = 'none';
    };
})();