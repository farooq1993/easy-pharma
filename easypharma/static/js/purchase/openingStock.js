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
    const name = document.getElementById('quickName').value.trim();
    if (!name) {
        showToast('Medicine name is required', 'error');
        return;
    }

    const data = {
        product_name: name,
        packing: document.getElementById('quickPacking').value.trim(),
        conversion_factor: parseInt(document.getElementById('quickConv').value) || 1,
        tax_id: document.getElementById('quickTax').value || null,
        schedule_id: document.getElementById('quickSchedule').value || null,
        content_id: document.getElementById('quickContent').value || null,
        company_id: document.getElementById('quickCompany').value || null,
        type_id: document.getElementById('quickType').value || null,
        hsn_code: document.getElementById('quickHsn').value.trim() || null
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

            // Clear fields
            document.getElementById('quickName').value = '';
            document.getElementById('quickPacking').value = '';
            document.getElementById('quickHsn').value = '';
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

// Save Function
async function saveOpeningStock() {
    if (openingItems.length === 0) {
        return showToast('Please add at least one item', 'error');
    }

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

    try {
        const resp = await fetch("/opening/stock/entry/", {
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
        }
    } catch (e) {
        console.error(e);
        showToast('Server Error', 'error');
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
    if (product.batches && product.batches.length) {
        document.getElementById('newMrp').value = product.batches[0].mrp_pack || '';
    }
    resultsDiv.style.display = 'none';
    updateNewItemTotal();
    document.getElementById('newBatch').focus();
}

// Enter key on fields to add item
document.addEventListener('DOMContentLoaded', () => {
    updateNewItemTotal();
    const fields = ['newBatch','newExpiry','newQty','newPrice','newMrp','newTax'];
    fields.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addOpeningItem();
            }
        });
    });
});