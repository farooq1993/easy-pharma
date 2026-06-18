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
        _csvShowError('Sirf .csv files accepted hain.');
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
        document.getElementById('csvParseBtn').innerHTML = '<i class="fas fa-search me-1"></i> CSV Preview Karo';

        if (!data.success) {
            _csvShowError(data.error || 'CSV parse nahi ho saki.');
            return;
        }

        // Store data
        _csvParsedItems = data.items || [];
        _csvMissing     = data.missing_products || [];

        // Pre-fill invoice meta
        if (data.invoice_number) document.getElementById('csvInvoiceNumber').value = data.invoice_number;
        if (data.purchase_date)  document.getElementById('csvPurchaseDate').value  = data.purchase_date;

        // Supplier auto-select by name
        if (data.supplier_name) {
            const sel = document.getElementById('csvSupplierSelect');
            const match = Array.from(sel.options).find(o =>
                o.text.toLowerCase().includes(data.supplier_name.toLowerCase())
            );
            if (match) sel.value = match.value;
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
            _csvShowError('Koi bhi product nahi mila system mein. Pehle products create karo phir CSV dobara upload karo.');
            return;
        }
        if (_csvParsedItems.length === 0) {
            _csvShowError('CSV mein koi valid data nahi mila.');
            return;
        }

        _csvRenderPreviewTable(_csvParsedItems);
        _csvSetStep(2);

    } catch (err) {
        document.getElementById('csvParseProgress').classList.add('d-none');
        document.getElementById('csvParseBtn').disabled = false;
        document.getElementById('csvParseBtn').innerHTML = '<i class="fas fa-search me-1"></i> CSV Preview Karo';
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
    if (!confirm('Saare items remove kar dein?')) return;
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
        alert('Koi items nahi hain load karne ke liye.');
        return;
    }

    // Validate invoice meta
    const suppVal  = document.getElementById('csvSupplierSelect').value;
    const invNum   = document.getElementById('csvInvoiceNumber').value.trim();
    const invDate  = document.getElementById('csvPurchaseDate').value;
    const payMode  = document.getElementById('csvPaymentMode').value;

    if (!suppVal) {
        document.getElementById('csvSupplierSelect').focus();
        showToast('Supplier select karo', 'error');
        return;
    }
    if (!invNum) {
        document.getElementById('csvInvoiceNumber').focus();
        showToast('Invoice number daalo', 'error');
        return;
    }

    // ── Fill main purchase form ──────────────
    // 1. Supplier
    const mainSupplierSel = document.getElementById('supplierSelect');
    mainSupplierSel.value = suppVal;
    mainSupplierSel.dispatchEvent(new Event('change'));
    // Sync supplier search input
    const suppSearchInput = document.getElementById('supplierSearchInput');
    if (suppSearchInput) {
        const selOpt = mainSupplierSel.options[mainSupplierSel.selectedIndex];
        if (selOpt) suppSearchInput.value = selOpt.text.split(' | ')[0];
    }

    // 2. Invoice details
    document.getElementById('invoiceNumber').value = invNum;
    if (invDate) document.getElementById('purchaseDate').value = invDate;
    document.getElementById('summaryPaymentMode').value = payMode;

    // 3. Load items into global items array
    // Fix expiry_date: ensure YYYY-MM-DD format (day as 01)
    _csvParsedItems.forEach(item => {
        if (item.expiry_date) {
            const ed = String(item.expiry_date).trim();
            if (ed.length === 7) {
                // YYYY-MM → YYYY-MM-01
                item.expiry_date = ed + '-01';
            } else if (/^\d{2}\/\d{4}$/.test(ed)) {
                // MM/YYYY → YYYY-MM-01
                const [mm, yyyy] = ed.split('/');
                item.expiry_date = `${yyyy}-${mm}-01`;
            }
        }
        // Ensure required fields
        if (!item.tax_amount) {
            const sub = (item.quantity||0) * (item.purchase_price||0);
            item.tax_amount = sub * (item.tax_percentage||0) / 100;
        }
        if (!item.total) {
            const sub = (item.quantity||0) * (item.purchase_price||0);
            item.total = sub + (item.tax_amount||0);
        }
        if (!item.total_units) {
            item.total_units = (item.quantity + (item.free_quantity||0)) * (item.conversion_factor||1);
        }
        if (!item.sale_price && item.mrp) {
            item.sale_price = item.mrp;
        }
        items.push(item);
    });

    // 4. Render table & summary
    renderTable();
    calculateSummary();

    // 5. Close modal
    bootstrap.Modal.getInstance(document.getElementById('csvImportModal')).hide();
    resetCsvImportModal();

    showToast(`${_csvParsedItems.length} items CSV se load ho gaye ✓`, 'success');

    // Scroll to items table
    setTimeout(() => {
        const tableEl = document.getElementById('purchaseTable');
        if (tableEl) tableEl.scrollIntoView({ behavior:'smooth', block:'start' });
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