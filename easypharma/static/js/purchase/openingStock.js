// ==================== QUICK SELECT WIDGET ====================
(function() {
    function initQuickSelect(selectId) {
        const sel = document.getElementById(selectId);
        const input = document.getElementById('qs-input-' + selectId);
        const drop = document.getElementById('qs-drop-' + selectId);
        const clearBtn = document.getElementById('qs-clear-' + selectId);
        if (!sel || !input) return;

        function getOptions() {
            return Array.from(sel.options).filter(o => o.value).map(o => ({value: o.value, text: o.text.trim()}));
        }

        function renderDrop(opts) {
            drop.innerHTML = '';
            opts.forEach(opt => {
                const div = document.createElement('div');
                div.className = 'qs-item';
                div.textContent = opt.text;
                div.onclick = () => {
                    sel.value = opt.value;
                    input.value = opt.text;
                    drop.style.display = 'none';
                    if (clearBtn) clearBtn.style.display = 'inline-block';
                };
                drop.appendChild(div);
            });
            drop.style.display = 'block';
        }

        input.addEventListener('focus', () => renderDrop(getOptions()));
        input.addEventListener('input', () => {
            const q = input.value.toLowerCase();
            const filtered = getOptions().filter(o => o.text.toLowerCase().includes(q));
            renderDrop(filtered);
        });

        window.qsClear = function(id) {
            document.getElementById(id).value = '';
            const inp = document.getElementById('qs-input-' + id);
            if (inp) inp.value = '';
            const btn = document.getElementById('qs-clear-' + id);
            if (btn) btn.style.display = 'none';
        };
    }

    document.addEventListener('DOMContentLoaded', () => {
        ['quickTax', 'quickSchedule', 'quickContent', 'quickCompany', 'quickType'].forEach(initQuickSelect);
    });
})();

// Quick Add Product Handler
async function handleSaveQuickProduct() {
    const name = (document.getElementById('quickName') || {}).value?.trim();
    if (!name) {
        showToast('Medicine name is required', 'error');
        return;
    }

    const data = {
        name: name,
        packing: (document.getElementById('quickPacking') || {}).value?.trim() || '',
        conversion_factor: parseInt((document.getElementById('quickConv') || {}).value) || 1,
        tax_id: (document.getElementById('quickTax') || {}).value || null,
        schedule_id: (document.getElementById('quickSchedule') || {}).value || null,
        content_id: (document.getElementById('quickContent') || {}).value || null,
        company_id: (document.getElementById('quickCompany') || {}).value || null,
        type_id: (document.getElementById('quickType') || {}).value || null,
        hsn_code: (document.getElementById('quickHsn') || {}).value?.trim() || null
    };

    try {
        const res = await fetch("/api/products/quick-add/", {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        });

        const result = await res.json();

        if (result.success) {
            showToast('Medicine added successfully!', 'success');
            
            const modal = bootstrap.Modal.getInstance(document.getElementById('quickAddModal'));
            if (modal) modal.hide();

            // Clear modal fields
            document.getElementById('quickName').value = '';
            document.getElementById('quickPacking').value = '';
            document.getElementById('quickHsn').value = '';
            ['quickTax','quickSchedule','quickContent','quickCompany','quickType'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
                typeof qsClear === 'function' && qsClear(id);
            });

            // Auto-select the newly created product
            const searchInput = document.getElementById('newProductSearch');
            if (searchInput) {
                searchInput.value = result.name;
                try {
                    const resp = await fetch(`/api/products/search/?q=${encodeURIComponent(result.name)}`);
                    const products = await resp.json();
                    const matched = products.find(p => p.id === result.id) || products[0];
                    if (matched) {
                        selectProductForOpening(matched);
                    }
                } catch (err) {
                    console.error('Failed to auto-select quick added product', err);
                }
            }
        } else {
            showToast(result.error || 'Failed to save medicine', 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('Error saving product. Check console.', 'error');
    }
}

// ==================== MAIN VARIABLES ====================
let openingItems = [];
let selectedProductForAdd = null;
let currentSearchResults = [];
let searchSelectedIndex = -1;
let masterAddModal;

// const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

// Toast
function showToast(msg, type = 'success') {
    const toast = document.getElementById('epToast');
    toast.innerHTML = `<i class="fas fa-${type==='error'?'exclamation':'check'}-circle"></i> ${msg}`;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 2500);
}

// Update Total
function updateNewItemTotal() {
    const qty = parseFloat(document.getElementById('newQty').value) || 0;
    const price = parseFloat(document.getElementById('newPrice').value) || 0;
    const tax = parseFloat(document.getElementById('newTax').value) || 0;

    const subtotal = qty * price;
    const taxAmt = subtotal * (tax / 100);
    const total = subtotal + taxAmt;

    const el = document.getElementById('newTotalDisplay');
    el.textContent = '₹' + total.toFixed(2);
}

// Add Item
function addOpeningItem() {
    const productName = document.getElementById('newProductSearch').value.trim();
    if (!productName) {
        showToast('Please select a medicine', 'error');
        return;
    }

    const item = {
        product_id: selectedProductForAdd ? selectedProductForAdd.id : null,
        product_name: productName,
        batch_number: document.getElementById('newBatch').value.trim() || 'OPENING',
        expiry_date: document.getElementById('newExpiry').value.trim(),
        quantity: parseFloat(document.getElementById('newQty').value) || 0,
        purchase_price: parseFloat(document.getElementById('newPrice').value) || 0,
        mrp: parseFloat(document.getElementById('newMrp').value) || 0,
        tax_percentage: parseFloat(document.getElementById('newTax').value) || 5,
    };

    if (item.quantity <= 0) {
        showToast('Quantity must be greater than 0', 'error');
        return;
    }

    const subtotal = item.quantity * item.purchase_price;
    item.tax_amount = subtotal * (item.tax_percentage / 100);
    item.total = subtotal + item.tax_amount;

    openingItems.push(item);
    renderOpeningTable();
    updateSummary();
    clearAddRow();
    showToast('Item added successfully');
}

function clearAddRow() {
    document.getElementById('newProductSearch').value = '';
    document.getElementById('newBatch').value = '';
    document.getElementById('newExpiry').value = '';
    document.getElementById('newQty').value = '1';
    document.getElementById('newPrice').value = '';
    document.getElementById('newMrp').value = '';
    document.getElementById('newTax').value = '5';
    selectedProductForAdd = null;
    const productInfo = document.getElementById('productInfo');
    if (productInfo) {
        productInfo.innerHTML = '';
        productInfo.style.display = 'none';
    }
    updateNewItemTotal();
}

function renderOpeningTable() {
    const tbody = document.getElementById('openingItemsBody');
    tbody.innerHTML = '';

    if (openingItems.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center py-4 text-muted">No items added yet.</td></tr>`;
        return;
    }

    openingItems.forEach((item, idx) => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${item.product_name}</td>
            <td>${item.batch_number}</td>
            <td>${item.expiry_date || '-'}</td>
            <td>${item.quantity}</td>
            <td>₹${parseFloat(item.purchase_price).toFixed(2)}</td>
            <td>₹${parseFloat(item.mrp).toFixed(2)}</td>
            <td>${item.tax_percentage}%</td>
            <td class="fw-bold text-end">₹${parseFloat(item.total).toFixed(2)}</td>
            <td><button onclick="removeOpeningItem(${idx})" class="btn btn-sm btn-danger"><i class="fas fa-trash"></i></button></td>
        `;
        tbody.appendChild(row);
    });
}

window.removeOpeningItem = function(idx) {
    openingItems.splice(idx, 1);
    renderOpeningTable();
    updateSummary();
};

function updateSummary() {
    let subTotal = 0, taxTotal = 0;
    openingItems.forEach(item => {
        subTotal += (item.quantity * item.purchase_price);
        taxTotal += (item.tax_amount || 0);
    });
    const grand = subTotal + taxTotal;

    document.getElementById('summarySubTotal').textContent = '₹' + subTotal.toFixed(2);
    document.getElementById('summaryTax').textContent = '₹' + taxTotal.toFixed(2);
    document.getElementById('summaryGrandTotal').textContent = '₹' + grand.toFixed(2);
}
// ==================== CSRF TOKEN (Fixed) ====================
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

const csrfToken = getCookie('csrftoken');

function showLoader(message = 'Please wait...') {
    const loader = document.getElementById('universalLoader');
    if (!loader) return;
    const loaderText = loader.querySelector('.loader-text');
    if (loaderText) {
        loaderText.innerText = message;
    }
    loader.classList.remove('d-none');
    loader.setAttribute('aria-busy', 'true');
}

function hideLoader() {
    const loader = document.getElementById('universalLoader');
    if (!loader) return;
    loader.classList.add('d-none');
    loader.setAttribute('aria-busy', 'false');
}

// Save Function
async function saveOpeningStock() {
    if (openingItems.length === 0) {
        return showToast('Please add at least one item', 'error');
    }

    const saveBtn = document.querySelector('.btn-complete');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.classList.add('disabled');
    }
    showLoader('Saving opening stock...');

    const data = {
        opening_stock_date: document.getElementById('opening_date').value,
        sub_total: parseFloat(document.getElementById('summarySubTotal').textContent.replace(/[^0-9.-]+/g,"") || 0),
        tax_amount: parseFloat(document.getElementById('summaryTax').textContent.replace(/[^0-9.-]+/g,"") || 0),
        total_amount: parseFloat(document.getElementById('summaryGrandTotal').textContent.replace(/[^0-9.-]+/g,"") || 0),
        items: openingItems.map(item => ({
            product_id: item.product_id,
            batch_number: item.batch_number,
            expiry_date: item.expiry_date,           // Keep as is (e.g. "01-28")
            quantity: item.quantity,
            purchase_price: item.purchase_price,
            mrp: item.mrp,
            tax_percentage: item.tax_percentage,
            total: item.total
        }))
    };

    const url = window.openingStockSaveUrl || "/opening/stock/entry/";

    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        });

        const result = await resp.json();

        if (result.success) {
            showToast(`✅ Saved! Voucher: ${result.voucher_number}`, 'success');
            setTimeout(() => window.location.href = "/opening/stock/list/", 1500);
        } else {
            showToast(result.error || 'Failed to save', 'error');
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.classList.remove('disabled');
            }
            hideLoader();
        }
    } catch (e) {
        console.error(e);
        showToast('Server Error', 'error');
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.classList.remove('disabled');
        }
        hideLoader();
    }
}

// ==================== PRODUCT SEARCH WITH KEYBOARD ====================
const searchInput = document.getElementById('newProductSearch');
const resultsDiv = document.getElementById('newSearchResults');

searchInput.addEventListener('input', async function () {
    const query = this.value.trim();
    searchSelectedIndex = -1;
    currentSearchResults = [];

    if (query.length < 2) {
        resultsDiv.style.display = 'none';
        return;
    }

    try {
        const resp = await fetch(`/api/products/search/?q=${encodeURIComponent(query)}`);
        currentSearchResults = await resp.json();

        resultsDiv.innerHTML = '';

        if (currentSearchResults.length > 0) {
            currentSearchResults.forEach((p, i) => {
                const div = document.createElement('div');
                div.className = 'search-item';
                div.innerHTML = `<strong>${p.name}</strong><br><small>${p.packing || ''} • ${p.company || ''} • GST ${p.tax_rate}%</small>`;
                div.onclick = () => selectProductForOpening(p);
                resultsDiv.appendChild(div);
            });
            searchSelectedIndex = 0;
            highlightSelected();
        } else {
            resultsDiv.innerHTML = `<div class="p-4 text-center text-muted">No matches.<br>Try Quick Add.</div>`;
        }
        resultsDiv.style.display = 'block';
    } catch (e) {
        resultsDiv.innerHTML = `<div class="p-4 text-danger">Search error</div>`;
        resultsDiv.style.display = 'block';
    }
});

function highlightSelected() {
    const items = resultsDiv.querySelectorAll('.search-item');
    items.forEach((el, i) => el.classList.toggle('selected', i === searchSelectedIndex));
}

searchInput.addEventListener('keydown', function(e) {
    if (resultsDiv.style.display === 'none') return;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        searchSelectedIndex = Math.min(searchSelectedIndex + 1, currentSearchResults.length - 1);
        highlightSelected();
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        searchSelectedIndex = Math.max(searchSelectedIndex - 1, 0);
        highlightSelected();
    } else if (e.key === 'Enter') {
        e.preventDefault();
        if (currentSearchResults[searchSelectedIndex]) {
            selectProductForOpening(currentSearchResults[searchSelectedIndex]);
        }
    } else if (e.key === 'Escape') {
        resultsDiv.style.display = 'none';
    }
});

function selectProductForOpening(product) {
    selectedProductForAdd = product;
    searchInput.value = product.name;
    document.getElementById('newTax').value = product.tax_rate || 5;
    
    // Default MRP to unit MRP if conversion_factor > 1, otherwise pack MRP
    const conv = parseInt(product.conversion_factor) || 1;
    if (product.batches && product.batches.length) {
        const mrpPack = parseFloat(product.batches[0].mrp_pack) || 0;
        const unitMrp = conv > 1 ? (mrpPack / conv) : mrpPack;
        document.getElementById('newMrp').value = unitMrp > 0 ? unitMrp.toFixed(2) : '';
    } else {
        document.getElementById('newMrp').value = '';
    }
    
    // Auto-calculate purchase price as 20% less than MRP
    const mrpVal = parseFloat(document.getElementById('newMrp').value) || 0;
    if (mrpVal > 0) {
        document.getElementById('newPrice').value = (mrpVal * 0.8).toFixed(2);
    } else {
        document.getElementById('newPrice').value = '';
    }

    // Display productInfo bar with Edit button
    const productInfo = document.getElementById('productInfo');
    if (productInfo) {
        productInfo.innerHTML = `
            <div class="d-flex justify-content-between align-items-center w-100 py-1" style="background: #f8fafc; padding: 4px 10px; border-radius: 6px; border: 1px solid #e2e8f0; margin-top: 5px;">
                <div id="productInfoText"><i class="fas fa-info-circle text-primary"></i> ${product.packing || 'Standard'} | Conv:×${conv} | GST:${product.tax_rate}%</div>
                <button type="button" class="btn btn-outline-primary btn-sm py-0 px-2 rounded fw-bold" style="font-size:0.7rem; height:20px; line-height:18px;" onclick="openEditProductModal()">
                    <i class="fas fa-edit me-1"></i>Edit Product
                </button>
            </div>
        `;
        productInfo.style.display = 'block';
    }

    resultsDiv.style.display = 'none';
    updateNewItemTotal();
    document.getElementById('newBatch').focus();
}

// Enter key on fields to add item & dynamic update listeners
document.addEventListener('DOMContentLoaded', () => {
    updateNewItemTotal();
    const fields = ['newBatch','newExpiry','newQty','newPrice','newMrp','newTax'];
    fields.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('keydown', e => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    addOpeningItem();
                }
            });
            // Update total dynamically when values change
            if (['newQty', 'newPrice', 'newTax'].includes(id)) {
                el.addEventListener('input', updateNewItemTotal);
            }
        }
    });

    // Auto-calculate purchase price when MRP changes manually
    const mrpInput = document.getElementById('newMrp');
    if (mrpInput) {
        mrpInput.addEventListener('input', () => {
            const mrpVal = parseFloat(mrpInput.value) || 0;
            if (mrpVal > 0) {
                const purPriceInput = document.getElementById('newPrice');
                if (purPriceInput) {
                    purPriceInput.value = (mrpVal * 0.8).toFixed(2);
                }
            }
            updateNewItemTotal();
        });
    }

    // Initialize master add modal
    const masterAddModalEl = document.getElementById('masterAddModal');
    if (masterAddModalEl) {
        masterAddModal = new bootstrap.Modal(masterAddModalEl);

        // Handle nested z-index for masterAddModal
        masterAddModalEl.addEventListener('show.bs.modal', function () {
            masterAddModalEl.style.zIndex = '1070';
            setTimeout(() => {
                const backdrops = document.querySelectorAll('.modal-backdrop');
                if (backdrops.length > 1) {
                    backdrops[backdrops.length - 1].style.zIndex = '1065';
                }
            }, 10);
        });

        masterAddModalEl.addEventListener('hidden.bs.modal', function () {
            // Restore overflow on body if quickAddModal is still open
            if (document.getElementById('quickAddModal').classList.contains('show')) {
                setTimeout(() => {
                    document.body.classList.add('modal-open');
                }, 100);
            }
        });
    }
});

// ==================== EDIT PRODUCT MODAL LOGIC ====================
window.openEditProductModal = function() {
    if (!selectedProductForAdd) { showToast('Select a product first', 'error'); return; }
    const p = selectedProductForAdd;

    document.getElementById('editProdId').value      = p.id;
    document.getElementById('editProdName').value    = p.name;
    document.getElementById('editProdPacking').value = p.packing || '';
    document.getElementById('editProdConv').value    = p.conversion_factor || 1;
    document.getElementById('editProdHsn').value     = p.hsn_code || '';
    document.getElementById('editProdSubtitle').textContent =
        'Editing: ' + p.name + ' — changes apply instantly';
    document.getElementById('editProdFeedback').style.display = 'none';

    // Pre-select Tax
    const taxSel = document.getElementById('editProdTax');
    let matched = false;
    Array.from(taxSel.options).forEach(opt => {
        const rate = parseFloat(opt.dataset.rate);
        if (!isNaN(rate) && rate === parseFloat(p.tax_rate || p.tax)) {
            taxSel.value = opt.value;
            matched = true;
        }
    });
    if (!matched) taxSel.value = '';

    // Pre-select Schedule & Company
    const schedSel = document.getElementById('editProdSchedule');
    schedSel.value = p.schedule_id || '';
    const compSel = document.getElementById('editProdCompany');
    compSel.value = p.company_id || '';

    bootstrap.Modal.getOrCreateInstance(document.getElementById('editProductModal')).show();
};

window.saveEditProduct = async function() {
    const id = document.getElementById('editProdId').value;
    if (!id) return;

    const packing   = document.getElementById('editProdPacking').value.trim();
    const conv      = parseFloat(document.getElementById('editProdConv').value) || 1;
    const taxId     = document.getElementById('editProdTax').value || null;
    const schedId   = document.getElementById('editProdSchedule').value || null;
    const compId    = document.getElementById('editProdCompany').value || null;
    const hsn       = document.getElementById('editProdHsn').value.trim() || null;

    const taxSel    = document.getElementById('editProdTax');
    const selOpt    = taxSel.options[taxSel.selectedIndex];
    const newTaxRate = selOpt && selOpt.dataset.rate ? parseFloat(selOpt.dataset.rate) : null;

    const saveBtn = document.getElementById('editProdSaveBtn');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Saving...';

    const feedback = document.getElementById('editProdFeedback');

    try {
        const resp = await fetch(`/api/products/quick-add/${id}/`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({
                packing,
                conversion_factor: conv,
                tax_id:     taxId,
                schedule_id: schedId,
                company_id:  compId,
                hsn_code:    hsn,
            })
        });
        const res = await resp.json();

        if (!resp.ok || !res.success) {
            feedback.className = 'alert alert-danger py-2';
            feedback.innerHTML = '<i class="fas fa-exclamation-circle me-1"></i>' + (res.error || 'Could not update product');
            feedback.style.display = 'block';
        } else {
            // Update in-memory selectedProductForAdd
            selectedProductForAdd.packing           = packing;
            selectedProductForAdd.conversion_factor = conv;
            selectedProductForAdd.hsn_code          = hsn;
            if (newTaxRate !== null) {
                selectedProductForAdd.tax_rate = newTaxRate;
                selectedProductForAdd.tax = newTaxRate;
            }
            if (schedId) selectedProductForAdd.schedule_id = schedId;
            if (compId)   selectedProductForAdd.company_id  = compId;

            // Sync the GST field in the Add form
            if (newTaxRate !== null) {
                document.getElementById('newTax').value = newTaxRate;
            }

            // Update productInfo bar text
            const infoText = document.getElementById('productInfoText');
            if (infoText) {
infoText.innerHTML = `<i class="fas fa-info-circle"></i> ${packing || 'Standard'} | Conv:×${conv} | GST:${newTaxRate !== null ? newTaxRate : selectedProductForAdd.tax_rate}%`;
            }

            // Recompute new item total in case tax changed
            updateNewItemTotal();
 
            showToast(`"${selectedProductForAdd.name}" updated successfully`);
            bootstrap.Modal.getInstance(document.getElementById('editProductModal')).hide();
        }
    } catch (err) {
        feedback.className = 'alert alert-danger py-2';
        feedback.innerHTML = '<i class="fas fa-exclamation-circle me-1"></i>' + err.message;
        feedback.style.display = 'block';
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-save me-1"></i> Save & Apply';
    }
};

// ==================== MASTER ADD MODAL LOGIC ====================
window.openMasterAddModal = function(masterType, selectId, title, fieldName) {
    document.getElementById('masterAddType').value = masterType;
    document.getElementById('masterSelectId').value = selectId;
    document.getElementById('masterFieldName').value = fieldName;
    document.getElementById('masterAddTitle').innerHTML = `<i class="fas fa-plus-circle me-2" style="color:var(--brand);"></i>Add ${title}`;
    document.getElementById('masterAddLabel').innerText = `${title} Name *`;
    document.getElementById('masterAddValue').value = '';
    document.getElementById('masterAddExtraValue').value = '';

    const extraRow = document.getElementById('masterAddExtraRow');
    const extraLabel = document.getElementById('masterAddExtraLabel');
    if (masterType === 'product-tax') {
        extraLabel.innerText = 'Tax Rate (%)';
        document.getElementById('masterAddExtraValue').type = 'number';
        document.getElementById('masterAddExtraValue').placeholder = 'Enter tax rate';
        extraRow.style.display = 'block';
    } else if (masterType === 'drug-company') {
        extraLabel.innerText = 'Short Name';
        document.getElementById('masterAddExtraValue').type = 'text';
        document.getElementById('masterAddExtraValue').placeholder = 'Enter short name';
        extraRow.style.display = 'block';
    } else {
        extraRow.style.display = 'none';
    }

    if (masterAddModal) masterAddModal.show();
};

window.submitMasterAdd = async function() {
    const masterType = document.getElementById('masterAddType').value;
    const selectId = document.getElementById('masterSelectId').value;
    const fieldName = document.getElementById('masterFieldName').value;
    const value = document.getElementById('masterAddValue').value.trim();
    const extraValue = document.getElementById('masterAddExtraValue').value.trim();

    if (!value) {
        showToast('Please enter a value', 'error');
        return;
    }

    const formData = new FormData();
    formData.append(fieldName, value);
    formData.append('csrfmiddlewaretoken', csrfToken);

    if (masterType === 'product-tax') {
        const taxRateToSend = extraValue || value;
        formData.append('tax_rate', taxRateToSend);
    }
    if (masterType === 'drug-company') {
        formData.append('sht_name', extraValue);
    }

    const saveBtn = document.getElementById('masterAddSaveBtn');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Saving';

    try {
        const response = await fetch(`/type/${masterType}/`, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: formData
        });
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Unable to save');
        }

        let selectEl = document.getElementById(selectId);
        if (!selectEl && selectId) {
            const selectIdLower = selectId.toLowerCase();
            selectEl = Array.from(document.querySelectorAll('select')).find(el => el.id.toLowerCase() === selectIdLower);
        }
        if (selectEl) {
            const actualSelectId = selectEl.id;
            if (selectEl.tomselect) {
                selectEl.tomselect.addOption({ value: String(data.id), text: data.name });
                selectEl.tomselect.refreshOptions(false);
                selectEl.tomselect.setValue(String(data.id));
            } else {
                const option = new Option(data.name, data.id, true, true);
                selectEl.add(option);
                selectEl.value = String(data.id);
                
                // Update visual QuickSelect input and clear button using the correct case-sensitive ID
                const visualInput = document.getElementById('qs-input-' + actualSelectId);
                if (visualInput) {
                    visualInput.value = data.name;
                }
                const clearBtn = document.getElementById('qs-clear-' + actualSelectId);
                if (clearBtn) {
                    clearBtn.style.display = 'inline-block';
                }
            }
        }

        if (masterAddModal) masterAddModal.hide();
        showToast(`${data.name} added successfully`);
    } catch (err) {
        showToast(err.message || 'Save failed', 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-save me-1"></i> Save';
    }
};