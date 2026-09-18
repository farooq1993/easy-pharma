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

        // Stacked Modal Fix for nested modals (Quick Add, Master Add, Edit Item) over OCR Modal
        ['quickAddModal', 'masterAddModal', 'editItemModal'].forEach(id => {
            const modalEl = document.getElementById(id);
            if (!modalEl) return;

            modalEl.addEventListener('show.bs.modal', function() {
                const openBackdrops = document.querySelectorAll('.modal-backdrop').length;
                const baseZ = 1060 + (openBackdrops * 20);

                modalEl.style.zIndex = baseZ + 10;

                setTimeout(() => {
                    const backdrops = document.querySelectorAll('.modal-backdrop');
                    const thisBackdrop = backdrops[backdrops.length - 1];
                    if (thisBackdrop) thisBackdrop.style.zIndex = baseZ;
                }, 0);
            });

            modalEl.addEventListener('hidden.bs.modal', function() {
                modalEl.style.zIndex = '';
                if (document.querySelectorAll('.modal.show').length > 0) {
                    document.body.classList.add('modal-open');
                }
            });
        });
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

            // If triggered from OCR Quick Add
            if (window._openingOcrQuickAddMissingIndex !== undefined && window._openingOcrQuickAddMissingIndex !== null) {
                const missingIdx = window._openingOcrQuickAddMissingIndex;
                window._openingOcrQuickAddMissingIndex = null;
                
                if (typeof _openingOcrMissingProducts !== 'undefined' && _openingOcrMissingProducts[missingIdx]) {
                    const missingItem = _openingOcrMissingProducts[missingIdx];
                    _openingOcrMissingProducts.splice(missingIdx, 1);
                    _openingOcrParsedItems.push({
                        product_id: result.id,
                        name: result.name,
                        batch_number: missingItem.batch_number || 'OPENING',
                        expiry_date: missingItem.expiry_date || '',
                        quantity: missingItem.quantity || 1,
                        purchase_price: missingItem.purchase_price || 0,
                        mrp: missingItem.mrp || 0,
                        tax_percentage: missingItem.tax_percentage || 5,
                        total: missingItem.total || (missingItem.quantity * missingItem.purchase_price)
                    });
                    
                    _openingOcrRenderMissingProducts(_openingOcrMissingProducts);
                    _openingOcrRenderPreviewTable(_openingOcrParsedItems);
                }
            }

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

// ==================== EDIT ITEM MODAL ====================
// Opens a modal pre-filled with the item's data so it can be edited
window.editOpeningItem = function(idx) {
    const item = openingItems[idx];
    if (!item) return;

    document.getElementById('editModalIndex').value = idx;
    document.getElementById('editModalProductName').value = item.product_name || '';
    document.getElementById('editModalBatch').value = item.batch_number || '';
    document.getElementById('editModalExpiry').value = item.expiry_date || '';
    document.getElementById('editModalQty').value = item.quantity;
    document.getElementById('editModalMrp').value = item.mrp;
    document.getElementById('editModalPrice').value = item.purchase_price;
    document.getElementById('editModalTax').value = item.tax_percentage;

    updateEditModalTotal();

    bootstrap.Modal.getOrCreateInstance(document.getElementById('editItemModal')).show();
};

// Recalculate the live total shown inside the edit modal
function updateEditModalTotal() {
    const qty = parseFloat(document.getElementById('editModalQty').value) || 0;
    const price = parseFloat(document.getElementById('editModalPrice').value) || 0;
    const tax = parseFloat(document.getElementById('editModalTax').value) || 0;

    const subtotal = qty * price;
    const taxAmt = subtotal * (tax / 100);
    const total = subtotal + taxAmt;

    const el = document.getElementById('editModalTotalDisplay');
    if (el) el.textContent = '₹' + total.toFixed(2);
}

// Wire up live total updates inside the edit modal once the DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    ['editModalQty', 'editModalPrice', 'editModalTax'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', updateEditModalTotal);
    });
});

// Save the edited values back into openingItems[idx]
window.saveEditedItem = function() {
    const idx = parseInt(document.getElementById('editModalIndex').value, 10);
    if (isNaN(idx) || !openingItems[idx]) return;

    const qty = parseFloat(document.getElementById('editModalQty').value) || 0;
    if (qty <= 0) {
        showToast('Quantity must be greater than 0', 'error');
        return;
    }

    const item = openingItems[idx];
    item.batch_number = document.getElementById('editModalBatch').value.trim() || 'OPENING';
    item.expiry_date = document.getElementById('editModalExpiry').value.trim();
    item.quantity = qty;
    item.mrp = parseFloat(document.getElementById('editModalMrp').value) || 0;
    item.purchase_price = parseFloat(document.getElementById('editModalPrice').value) || 0;
    item.tax_percentage = parseFloat(document.getElementById('editModalTax').value) || 0;

    const subtotal = item.quantity * item.purchase_price;
    item.tax_amount = subtotal * (item.tax_percentage / 100);
    item.total = subtotal + item.tax_amount;

    renderOpeningTable();
    updateSummary();

    const modalEl = document.getElementById('editItemModal');
    const modalInstance = bootstrap.Modal.getInstance(modalEl);
    if (modalInstance) modalInstance.hide();

    showToast('Item updated successfully');
};

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
    const searchInputEl = document.getElementById('newProductSearch');
    if (searchInputEl) {
        searchInputEl.focus();
    }
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
            <td>₹${parseFloat(item.mrp).toFixed(2)}</td>
            <td>₹${parseFloat(item.purchase_price).toFixed(2)}</td>
            <td>${item.tax_percentage}%</td>
            <td class="fw-bold text-end">₹${parseFloat(item.total).toFixed(2)}</td>
            <td class="text-nowrap">
                <button onclick="editOpeningItem(${idx})" class="btn btn-sm btn-primary me-1" title="Edit item"><i class="fas fa-edit"></i></button>
                <button onclick="removeOpeningItem(${idx})" class="btn btn-sm btn-danger" title="Delete item"><i class="fas fa-trash"></i></button>
            </td>
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

    const subEl = document.getElementById('summarySubTotal');
    const taxEl = document.getElementById('summaryTax');
    const grandEl = document.getElementById('summaryGrandTotal');
    if (subEl) subEl.textContent = '₹' + subTotal.toFixed(2);
    if (taxEl) taxEl.textContent = '₹' + taxTotal.toFixed(2);
    if (grandEl) grandEl.textContent = '₹' + grand.toFixed(2);

    if (typeof saveOpeningStockDraft === 'function') {
        saveOpeningStockDraft();
    }
}

// ── Opening Stock Draft Auto-Save & Recovery ──
function isOpeningStockEditMode() {
    return Boolean(window.openingStockSaveUrl || window.openingStockId || document.getElementById('editVoucherNumber') || document.getElementById('editVoucherBadge'));
}

function saveOpeningStockDraft() {
    if (isOpeningStockEditMode()) return;
    try {
        if (openingItems && openingItems.length > 0) {
            const draft = {
                opening_date: document.getElementById('opening_date')?.value || '',
                items: openingItems,
                timestamp: Date.now()
            };
            localStorage.setItem('easypharma_opening_stock_draft_v1', JSON.stringify(draft));
        } else {
            localStorage.removeItem('easypharma_opening_stock_draft_v1');
        }
    } catch (e) {
        console.warn('Failed to save opening stock draft', e);
    }
}

function clearOpeningStockDraft() {
    try {
        localStorage.removeItem('easypharma_opening_stock_draft_v1');
    } catch (e) {}
}

function restoreOpeningStockDraft() {
    if (isOpeningStockEditMode()) return;
    try {
        const raw = localStorage.getItem('easypharma_opening_stock_draft_v1');
        if (!raw) return;
        const draft = JSON.parse(raw);
        if (draft && Array.isArray(draft.items) && draft.items.length > 0) {
            openingItems = draft.items;
            if (draft.opening_date && document.getElementById('opening_date')) {
                document.getElementById('opening_date').value = draft.opening_date;
            }
            renderOpeningTable();
            updateSummary();
            showToast('⚡ Restored unsaved opening stock draft! <button type="button" class="btn btn-sm btn-outline-light ms-2" onclick="clearOpeningStockDraftAndReset()" style="padding:1px 6px;font-size:11px;">Clear Draft</button>', 'success');
        }
    } catch (e) {
        console.warn('Failed to restore opening stock draft', e);
    }
}

window.clearOpeningStockDraftAndReset = function() {
    clearOpeningStockDraft();
    openingItems = [];
    renderOpeningTable();
    updateSummary();
    showToast('Draft cleared', 'warning');
};

// Auto-save on date change & initial restore
document.addEventListener('DOMContentLoaded', function() {
    const dateEl = document.getElementById('opening_date');
    if (dateEl) {
        dateEl.addEventListener('change', saveOpeningStockDraft);
    }
    // Delay slightly to let editData load if in edit mode
    setTimeout(() => {
        if (!isOpeningStockEditMode() && openingItems.length === 0) {
            restoreOpeningStockDraft();
        }
    }, 100);
});

// Guard before unload
window.addEventListener('beforeunload', function(e) {
    if (window.__isOpeningStockSubmitting) return;
    saveOpeningStockDraft();
    if (openingItems && openingItems.length > 0) {
        e.preventDefault();
        e.returnValue = 'You have unsaved opening stock items. Are you sure you want to leave or refresh?';
        return e.returnValue;
    }
});

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
            window.__isOpeningStockSubmitting = true;
            clearOpeningStockDraft();
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

// What the user actually typed (preserved across arrow navigation)
let _userTypedQuery = '';
// Whether we are currently in arrow-preview mode
let _isNavigating = false;

searchInput.addEventListener('input', async function () {
    const query = this.value.trim();

    // User typed something — exit nav mode, update stored query
    _isNavigating = false;
    _userTypedQuery = this.value;
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
    items.forEach((el, i) => {
        el.classList.toggle('selected', i === searchSelectedIndex);
        if (i === searchSelectedIndex) {
            // Preview: show product name in input
            searchInput.value = currentSearchResults[i].name;
            // Cursor to end so it looks natural
            searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
            // Scroll item into view
            el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    });
}

function exitNavMode() {
    // Restore the original typed text and clear highlights
    _isNavigating = false;
    searchSelectedIndex = -1;
    searchInput.value = _userTypedQuery;
    const len = searchInput.value.length;
    searchInput.setSelectionRange(len, len);
    resultsDiv.querySelectorAll('.search-item').forEach(el => el.classList.remove('selected'));
}

searchInput.addEventListener('keydown', function(e) {
    if (resultsDiv.style.display === 'none') return;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (!_isNavigating) {
            // Enter nav mode — save current typed text first
            _userTypedQuery = searchInput.value;
            _isNavigating = true;
            searchSelectedIndex = -1;
        }
        searchSelectedIndex = Math.min(searchSelectedIndex + 1, currentSearchResults.length - 1);
        highlightSelected();

    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (!_isNavigating) return;
        if (searchSelectedIndex <= 0) {
            // Back to top — exit nav, restore typed text
            exitNavMode();
        } else {
            searchSelectedIndex--;
            highlightSelected();
        }

    } else if (e.key === 'Enter') {
        e.preventDefault();
        if (_isNavigating && currentSearchResults[searchSelectedIndex]) {
            selectProductForOpening(currentSearchResults[searchSelectedIndex]);
        } else if (!_isNavigating && currentSearchResults.length > 0) {
            // Enter without arrow nav — select first result
            selectProductForOpening(currentSearchResults[0]);
        }

    } else if (e.key === 'Escape') {
        exitNavMode();
        resultsDiv.style.display = 'none';

    } else if (_isNavigating) {
        // Any other key (backspace, letter, etc.) while in nav mode:
        // exit nav mode first (restores original typed text),
        // then let the browser handle the key normally on the restored text
        exitNavMode();
        // Don't preventDefault — browser will process the key on restored input
    }
});

function selectProductForOpening(product) {
    selectedProductForAdd = product;
    searchInput.value = product.name;
    document.getElementById('newTax').value = product.tax_rate || 5;
    
    // Clear MRP and Purchase Price — user must enter actual opening stock values
    document.getElementById('newMrp').value = '';
    document.getElementById('newPrice').value = '';

    // Display productInfo bar with Edit button
    const conv = parseInt(product.conversion_factor) || 1;
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
    const fields = ['newBatch', 'newExpiry', 'newQty', 'newMrp', 'newPrice', 'newTax'];
    fields.forEach((id, idx) => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('keydown', e => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    if (idx < fields.length - 1) {
                        const nextEl = document.getElementById(fields[idx + 1]);
                        if (nextEl) {
                            nextEl.focus();
                            nextEl.select();
                        }
                    } else {
                        addOpeningItem();
                    }
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

// ==================== OPENING STOCK AI OCR SCAN ====================
let _openingOcrSelectedFiles = [];
let _openingOcrParsedItems = [];
let _openingOcrMissingProducts = [];

function openingOcrDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    const dropZone = document.getElementById('openingOcrDropZone');
    if (dropZone) dropZone.style.background = '#e6fffa';
}

function openingOcrDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    const dropZone = document.getElementById('openingOcrDropZone');
    if (dropZone) dropZone.style.background = '#f0fdf9';
}

function openingOcrDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    openingOcrDragLeave(e);
    if (e.dataTransfer && e.dataTransfer.files.length > 0) {
        _openingOcrProcessFiles(Array.from(e.dataTransfer.files));
    }
}

function openingOcrFileSelected(input) {
    if (input && input.files && input.files.length > 0) {
        _openingOcrProcessFiles(Array.from(input.files));
    }
}

function _openingOcrProcessFiles(files) {
    _openingOcrSelectedFiles = files.filter(f => f.type.startsWith('image/'));
    if (_openingOcrSelectedFiles.length === 0) {
        showToast('Please select valid image files (JPG, PNG, etc.)', 'error');
        return;
    }

    const container = document.getElementById('openingOcrSelectedFile');
    if (container) {
        let html = '<div class="d-flex flex-wrap gap-2">';
        _openingOcrSelectedFiles.forEach((file) => {
            const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
            html += `
                <div class="d-flex align-items-center gap-2 px-3 py-2" style="background:#f0fdfa;border:1px solid #ccfbf1;border-radius:10px;font-size:0.83rem;">
                    <i class="fas fa-file-image text-teal" style="color:#0d9488;"></i>
                    <span class="fw-bold text-dark">${file.name}</span>
                    <span class="text-muted">(${sizeMB} MB)</span>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
        container.classList.remove('d-none');
    }

    const parseBtn = document.getElementById('openingOcrParseBtn');
    if (parseBtn) parseBtn.disabled = false;
}

async function submitOpeningOcrParse() {
    if (_openingOcrSelectedFiles.length === 0) return;

    const parseBtn = document.getElementById('openingOcrParseBtn');
    const progress = document.getElementById('openingOcrParseProgress');
    const errDiv = document.getElementById('openingOcrParseError');
    const statusText = document.getElementById('openingOcrProgressStatusText');

    if (parseBtn) parseBtn.disabled = true;
    if (progress) progress.classList.remove('d-none');
    if (errDiv) errDiv.classList.add('d-none');
    if (statusText) statusText.textContent = `AI OCR engine is reading ${_openingOcrSelectedFiles.length} page(s)...`;

    const formData = new FormData();
    _openingOcrSelectedFiles.forEach(file => {
        formData.append('stock_images', file);
    });

    try {
        const response = await fetch('/opening/stock/import/ocr/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken
            },
            body: formData
        });

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to scan opening stock image.');
        }

        const scansTodayEl = document.getElementById('openingOcrScansToday');
        const maxScansEl = document.getElementById('openingOcrMaxScans');
        if (scansTodayEl && data.scans_today !== undefined) scansTodayEl.textContent = data.scans_today;
        if (maxScansEl && data.max_scans !== undefined) maxScansEl.textContent = data.max_scans;

        _openingOcrParsedItems = data.items || [];
        _openingOcrMissingProducts = data.missing_products || [];

        _openingOcrRenderMissingProducts(_openingOcrMissingProducts);
        _openingOcrRenderPreviewTable(_openingOcrParsedItems);

        // Switch to Step 2
        document.getElementById('openingOcrStep1').classList.add('d-none');
        document.getElementById('openingOcrStep2').classList.remove('d-none');
        document.getElementById('openingOcrBackBtn').style.display = 'block';
        document.getElementById('openingOcrParseBtn').classList.add('d-none');
        document.getElementById('openingOcrConfirmBtn').classList.remove('d-none');

        document.getElementById('openingOcrStep1Ind').classList.remove('active');
        document.getElementById('openingOcrStep2Ind').classList.add('active');

    } catch (err) {
        if (errDiv) {
            document.getElementById('openingOcrParseErrorMsg').textContent = err.message || 'Scanning failed';
            errDiv.classList.remove('d-none');
        }
    } finally {
        if (progress) progress.classList.add('d-none');
        if (parseBtn) parseBtn.disabled = false;
    }
}

function _openingOcrRenderMissingProducts(missing) {
    const bar = document.getElementById('openingOcrMissingProductsBar');
    const list = document.getElementById('openingOcrMissingProductsList');
    if (!bar || !list) return;

    if (!missing || missing.length === 0) {
        bar.classList.add('d-none');
        list.innerHTML = '';
        return;
    }

    let html = '';
    missing.forEach((m, idx) => {
        html += `
            <div class="d-flex align-items-center justify-content-between p-2 rounded" style="background:#fff; border:1px solid #fef3c7;">
                <div>
                    <span class="fw-bold text-dark">${m.product}</span>
                    <span class="text-muted ms-2" style="font-size:0.75rem;">(Qty: ${m.quantity}, MRP: ₹${m.mrp})</span>
                </div>
                <button type="button" class="btn btn-sm btn-outline-warning rounded-pill px-3 py-1" style="font-size:0.78rem; font-weight:600;" onclick="openingOcrQuickAddProduct(${idx})">
                    <i class="fas fa-plus me-1"></i> Quick Add
                </button>
            </div>
        `;
    });

    list.innerHTML = html;
    bar.classList.remove('d-none');
}

function openingOcrQuickAddProduct(missingIdx) {
    const missingItem = _openingOcrMissingProducts[missingIdx];
    if (!missingItem) return;

    const nameInput = document.getElementById('quickName');
    if (nameInput) nameInput.value = missingItem.product;

    window._openingOcrQuickAddMissingIndex = missingIdx;

    const modalEl = document.getElementById('quickAddModal');
    if (modalEl) {
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
}

function _openingOcrRenderPreviewTable(items) {
    const tbody = document.getElementById('openingOcrPreviewTbody');
    const countEl = document.getElementById('openingOcrItemCount');
    if (!tbody) return;

    tbody.innerHTML = '';
    if (countEl) countEl.textContent = items.length;

    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="text-center py-4 text-muted">No items to preview.</td></tr>';
        _openingOcrRefreshTotals();
        return;
    }

    items.forEach((item, idx) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td data-label="#" style="padding:6px;">${idx + 1}</td>
            <td data-label="Medicine Name">
                <input type="text" class="form-control form-control-sm border-0 bg-transparent fw-bold" value="${item.name || ''}" onchange="_openingOcrUpdateItem(${idx}, 'name', this.value)">
            </td>
            <td data-label="Batch No">
                <input type="text" class="form-control form-control-sm text-uppercase" style="width:110px;" value="${item.batch_number || 'OPENING'}" onchange="_openingOcrUpdateItem(${idx}, 'batch_number', this.value)">
            </td>
            <td data-label="Expiry">
                <input type="text" class="form-control form-control-sm" style="width:90px;" placeholder="MM/YY" value="${item.expiry_date || ''}" onchange="_openingOcrUpdateItem(${idx}, 'expiry_date', this.value)">
            </td>
            <td data-label="Qty">
                <input type="number" class="form-control form-control-sm text-center" style="width:70px;" value="${item.quantity || 1}" min="1" onchange="_openingOcrUpdateItem(${idx}, 'quantity', this.value)">
            </td>
            <td data-label="Pur Rate">
                <input type="number" step="0.01" class="form-control form-control-sm text-end" style="width:90px;" value="${item.purchase_price || 0}" onchange="_openingOcrUpdateItem(${idx}, 'purchase_price', this.value)">
            </td>
            <td data-label="MRP">
                <input type="number" step="0.01" class="form-control form-control-sm text-end" style="width:80px;" value="${item.mrp || 0}" onchange="_openingOcrUpdateItem(${idx}, 'mrp', this.value)">
            </td>
            <td data-label="GST%">
                <input type="number" step="0.01" class="form-control form-control-sm text-center" style="width:60px;" value="${item.tax_percentage || 5}" onchange="_openingOcrUpdateItem(${idx}, 'tax_percentage', this.value)">
            </td>
            <td data-label="Total" class="text-end fw-bold text-teal" id="openingOcrRowTotal-${idx}">
                ₹${(item.total || 0).toFixed(2)}
            </td>
            <td>
                <button type="button" class="btn btn-sm btn-link text-danger p-0" onclick="_openingOcrRemoveRow(${idx})" title="Remove item">
                    <i class="fas fa-times"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    _openingOcrRefreshTotals();
}

function _openingOcrUpdateItem(idx, field, value) {
    const item = _openingOcrParsedItems[idx];
    if (!item) return;

    if (field === 'quantity') {
        item[field] = parseInt(value) || 0;
    } else if (field === 'purchase_price' || field === 'mrp' || field === 'tax_percentage') {
        item[field] = parseFloat(value) || 0.0;
    } else {
        item[field] = value.trim();
    }

    _openingOcrRecalcRow(idx);
    _openingOcrRefreshTotals();
}

function _openingOcrRecalcRow(idx) {
    const item = _openingOcrParsedItems[idx];
    if (!item) return;

    const qty = item.quantity || 0;
    const price = item.purchase_price || 0.0;
    const taxRate = item.tax_percentage || 0.0;

    const subtotal = qty * price;
    const taxAmt = subtotal * (taxRate / 100.0);
    item.total = subtotal + taxAmt;

    const cell = document.getElementById(`openingOcrRowTotal-${idx}`);
    if (cell) {
        cell.textContent = '₹' + item.total.toFixed(2);
    }
}

function _openingOcrRefreshTotals() {
    const totalQty = _openingOcrParsedItems.reduce((s, i) => s + (i.quantity || 0), 0);
    const totalAmt = _openingOcrParsedItems.reduce((s, i) => s + (i.total || 0), 0);
    const totalQtyEl = document.getElementById('openingOcrTotalQty');
    if (totalQtyEl) totalQtyEl.textContent = totalQty;
    const totalAmtEl = document.getElementById('openingOcrTotalAmount');
    if (totalAmtEl) totalAmtEl.textContent = '₹' + totalAmt.toFixed(2);

    const confirmBtn = document.getElementById('openingOcrConfirmBtn');
    if (confirmBtn) {
        confirmBtn.disabled = (_openingOcrParsedItems.length === 0);
    }
}

function _openingOcrRemoveRow(idx) {
    _openingOcrParsedItems.splice(idx, 1);
    _openingOcrRenderPreviewTable(_openingOcrParsedItems);
}

function openingOcrClearAll() {
    if (!confirm('Remove all extracted opening stock items?')) return;
    _openingOcrParsedItems = [];
    _openingOcrRenderPreviewTable([]);
}

function openingOcrGoToStep1() {
    document.getElementById('openingOcrStep2').classList.add('d-none');
    document.getElementById('openingOcrStep1').classList.remove('d-none');
    document.getElementById('openingOcrBackBtn').style.display = 'none';
    document.getElementById('openingOcrConfirmBtn').classList.add('d-none');
    document.getElementById('openingOcrParseBtn').classList.remove('d-none');

    document.getElementById('openingOcrStep2Ind').classList.remove('active');
    document.getElementById('openingOcrStep1Ind').classList.add('active');
}

function ocrConfirmAndLoadOpening() {
    if (_openingOcrParsedItems.length === 0) {
        showToast('No items to load', 'error');
        return;
    }

    _openingOcrParsedItems.forEach(item => {
        openingItems.push({
            product_id: item.product_id || null,
            product_name: item.name,
            batch_number: item.batch_number || 'OPENING',
            expiry_date: item.expiry_date || '',
            quantity: item.quantity || 1,
            mrp: item.mrp || 0,
            purchase_price: item.purchase_price || 0,
            tax_percentage: item.tax_percentage || 5,
            total: item.total || (item.quantity * item.purchase_price)
        });
    });

    renderOpeningTable();
    updateSummary();

    const modalEl = document.getElementById('openingOcrImportModal');
    if (modalEl) {
        const instance = bootstrap.Modal.getInstance(modalEl);
        if (instance) instance.hide();
    }

    showToast(`Loaded ${_openingOcrParsedItems.length} items into Opening Stock!`, 'success');
}

function resetOpeningOcrModal() {
    _openingOcrSelectedFiles = [];
    _openingOcrParsedItems = [];
    _openingOcrMissingProducts = [];

    const fileInput = document.getElementById('openingStockFile');
    const cameraInput = document.getElementById('openingStockCamera');
    if (fileInput) fileInput.value = '';
    if (cameraInput) cameraInput.value = '';

    const selFileDiv = document.getElementById('openingOcrSelectedFile');
    if (selFileDiv) {
        selFileDiv.innerHTML = '';
        selFileDiv.classList.add('d-none');
    }

    const parseBtn = document.getElementById('openingOcrParseBtn');
    if (parseBtn) parseBtn.disabled = true;

    openingOcrGoToStep1();
}

// Global window mappings
window.openingOcrDragOver = openingOcrDragOver;
window.openingOcrDragLeave = openingOcrDragLeave;
window.openingOcrDrop = openingOcrDrop;
window.openingOcrFileSelected = openingOcrFileSelected;
window.submitOpeningOcrParse = submitOpeningOcrParse;
window.openingOcrQuickAddProduct = openingOcrQuickAddProduct;
window._openingOcrUpdateItem = _openingOcrUpdateItem;
window._openingOcrRemoveRow = _openingOcrRemoveRow;
window.openingOcrClearAll = openingOcrClearAll;
window.openingOcrGoToStep1 = openingOcrGoToStep1;
window.ocrConfirmAndLoadOpening = ocrConfirmAndLoadOpening;
window.resetOpeningOcrModal = resetOpeningOcrModal;

// ==================== AI AUTO-FILL PRODUCT DETAILS ====================
async function aiAutoFillProductDetails() {
    const nameInput = document.getElementById('quickName');
    const name = nameInput ? nameInput.value.trim() : '';

    if (!name) {
        showToast('Please type a medicine name first.', 'error');
        return;
    }

    const btn = document.getElementById('btnAiAutoFill');
    const statusDiv = document.getElementById('aiAutoFillStatus');

    if (btn) btn.disabled = true;
    if (statusDiv) statusDiv.classList.remove('d-none');

    try {
        const response = await fetch('/api/products/ai-autofill/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ product_name: name })
        });

        const result = await response.json();

        if (!result.success) {
            throw new Error(result.error || 'Failed to auto-fill details.');
        }

        const data = result.data;

        // 1. Fill basic fields
        if (data.product_name && nameInput) nameInput.value = data.product_name;
        if (data.packing) document.getElementById('quickPacking').value = data.packing;
        if (data.conversion_factor) document.getElementById('quickConv').value = data.conversion_factor;
        if (data.hsn_code) document.getElementById('quickHsn').value = data.hsn_code;

        // Helper to update custom QuickSelect dropdown
        function updateQuickSelectOption(selectId, valueId, textName) {
            const selectEl = document.getElementById(selectId);
            if (!selectEl || !valueId) return;

            let optionExists = false;
            for (let i = 0; i < selectEl.options.length; i++) {
                if (selectEl.options[i].value == valueId) {
                    optionExists = true;
                    break;
                }
            }

            if (!optionExists && textName) {
                const opt = document.createElement('option');
                opt.value = valueId;
                opt.textContent = textName;
                selectEl.appendChild(opt);
            }

            selectEl.value = valueId;

            const visualInput = document.getElementById('qs-input-' + selectId);
            if (visualInput && textName) {
                visualInput.value = textName;
            }
            const clearBtn = document.getElementById('qs-clear-' + selectId);
            if (clearBtn) {
                clearBtn.style.display = 'inline-block';
            }
        }

        updateQuickSelectOption('quickType', data.type_id, data.type_name);
        updateQuickSelectOption('quickTax', data.tax_id, data.tax_name);
        updateQuickSelectOption('quickSchedule', data.schedule_id, data.schedule_name);
        updateQuickSelectOption('quickContent', data.content_id, data.content_name);
        updateQuickSelectOption('quickCompany', data.company_id, data.company_name);

        showToast('Medicine details auto-filled by AI!', 'success');
    } catch (err) {
        showToast(err.message || 'Error auto-filling details', 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (statusDiv) statusDiv.classList.add('d-none');
    }
}
window.aiAutoFillProductDetails = aiAutoFillProductDetails;
