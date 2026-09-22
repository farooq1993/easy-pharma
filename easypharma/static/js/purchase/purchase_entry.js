/**
 * ══════════════════════════════════════════════════════════════════════
 * EasyPharma - Purchase Entry Modular Engine
 * Architecture: Clean JS Module with DRY Utilities & Defensive State Management
 * ══════════════════════════════════════════════════════════════════════
 */

// Global Application State
window.items = [];
window.selectedProduct = null;
window.currentBatchHistory = [];
window.searchSelectedIndex = -1;
window.batchSelectedIndex = -1;
window.availableCreditNotes = [];
window.pendingCsvData = null;
window.pendingMissingProducts = [];
window.__isPurchaseSubmitting = false;

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
window.getCookie = getCookie;

function getCsrfToken() {
    let token = getCookie('csrftoken');
    if (!token) token = document.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
    if (!token) token = window.EP_CONFIG?.csrfToken;
    if (!token) token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    return token || '';
}
window.getCsrfToken = getCsrfToken;

/**
 * ══════════════════════════════════════════════════════════════════════
 * 1. UI FEEDBACK UTILITIES (Toast & Loader)
 * ══════════════════════════════════════════════════════════════════════
 */
let _epToastTimer = null;
function showToast(msg, type = 'success') {
    let toast = document.getElementById('epToast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'epToast';
        toast.className = 'ep-toast';
        document.body.appendChild(toast);
    }
    if (_epToastTimer) clearTimeout(_epToastTimer);
    const icon = type === 'error' ? '<i class="fas fa-exclamation-circle me-2"></i>' : '<i class="fas fa-check-circle me-2"></i>';
    toast.innerHTML = icon + '<span>' + msg + '</span>';
    toast.className = 'ep-toast ' + (type === 'error' ? 'error' : '');
    toast.classList.add('show');
    _epToastTimer = setTimeout(() => {
        toast.classList.remove('show');
    }, 4500);
}
window.showToast = showToast;

function showLoader(text = 'Please wait...') {
    const loader = document.getElementById('universalLoader');
    if (loader) {
        const textEl = loader.querySelector('.loader-text');
        if (textEl) textEl.textContent = text;
        loader.classList.remove('d-none');
        loader.setAttribute('aria-busy', 'true');
    }
}
window.showLoader = showLoader;

function hideLoader() {
    const loader = document.getElementById('universalLoader');
    if (loader) {
        loader.classList.add('d-none');
        loader.setAttribute('aria-busy', 'false');
    }
}
window.hideLoader = hideLoader;

/**
 * ══════════════════════════════════════════════════════════════════════
 * 2. EXPIRY DATE HELPER (Single Source of Truth for Expiry Parsing & Masking)
 * ══════════════════════════════════════════════════════════════════════
 */
const ExpiryDateHelper = {
    CURRENT_CENTURY: Math.floor(new Date().getFullYear() / 100) * 100,

    parse(raw) {
        if (!raw || typeof raw !== 'string') return null;
        const cleaned = raw.trim().replace(/[\/\.\s_]+/g, '-');
        let month = null;
        let year = null;

        if (cleaned.includes('-')) {
            const parts = cleaned.split('-').filter(Boolean);
            if (parts.length === 2) {
                const [p1, p2] = parts;
                if (p1.length === 4 && p2.length <= 2) {
                    year = parseInt(p1, 10);
                    month = parseInt(p2, 10);
                } else {
                    month = parseInt(p1, 10);
                    year = parseInt(p2, 10);
                }
            }
        } else {
            const digits = cleaned.replace(/\D/g, '');
            if (digits.length === 3) {
                month = parseInt(digits.substring(0, 1), 10);
                year = parseInt(digits.substring(1), 10);
            } else if (digits.length === 4) {
                month = parseInt(digits.substring(0, 2), 10);
                year = parseInt(digits.substring(2), 10);
            } else if (digits.length === 6) {
                const first4 = parseInt(digits.substring(0, 4), 10);
                if (first4 >= 2000 && first4 <= 2100) {
                    year = first4;
                    month = parseInt(digits.substring(4), 10);
                } else {
                    month = parseInt(digits.substring(0, 2), 10);
                    year = parseInt(digits.substring(2), 10);
                }
            }
        }

        if (month === null || year === null || isNaN(month) || isNaN(year)) return null;
        if (month < 1 || month > 12) return null;

        if (year < 100) year = this.CURRENT_CENTURY + year;
        if (year < 2000 || year > 2100) return null;

        const monthStr = String(month).padStart(2, '0');
        const shortYear = String(year).slice(-2);

        return {
            month,
            year,
            iso: `${year}-${monthStr}`,
            display: `${monthStr}-${shortYear}`
        };
    },

    formatDisplay(month, year) {
        if (!month || !year) return '';
        return `${String(month).padStart(2, '0')}-${String(year).slice(-2)}`;
    },

    attachAutoFormatter(inputEl, onSyncCallback) {
        if (!inputEl) return;
        let isDeleting = false;

        inputEl.addEventListener('keydown', (e) => {
            isDeleting = (e.key === 'Backspace' || e.key === 'Delete');
        });

        inputEl.addEventListener('input', () => {
            let val = inputEl.value;
            let raw = val.replace(/[^0-9\/\-\s]/g, '').replace(/[\/\s]+/g, '-');

            if (!isDeleting) {
                const digits = raw.replace(/\D/g, '');
                if (raw.indexOf('-') === -1) {
                    if (digits.length === 1 && parseInt(digits, 10) > 1) {
                        raw = `0${digits}-`;
                    } else if (digits.length === 2) {
                        const m = parseInt(digits, 10);
                        if (m >= 1 && m <= 12) {
                            raw = `${digits}-`;
                        }
                    } else if (digits.length === 3) {
                        raw = `0${digits[0]}-${digits.slice(1)}`;
                    } else if (digits.length >= 4) {
                        raw = `${digits.slice(0, 2)}-${digits.slice(2, 6)}`;
                    }
                }
            }

            inputEl.value = raw.slice(0, 7);
            if (typeof onSyncCallback === 'function') onSyncCallback();
        });

        inputEl.addEventListener('blur', () => {
            const parsed = ExpiryDateHelper.parse(inputEl.value);
            if (parsed) {
                inputEl.value = parsed.display;
            }
            if (typeof onSyncCallback === 'function') onSyncCallback();
        });
    }
};
window.ExpiryDateHelper = ExpiryDateHelper;
window.parseExpiryInput = function(raw) { return ExpiryDateHelper.parse(raw); };
window.formatExpiryDisplay = function(m, y) { return ExpiryDateHelper.formatDisplay(m, y); };

/**
 * ══════════════════════════════════════════════════════════════════════
 * 3. SEARCHABLE QUICK-SELECT DROPDOWN MANAGER
 * ══════════════════════════════════════════════════════════════════════
 */
function initQuickSelect(selectId) {
    const sel = document.getElementById(selectId);
    const input = document.getElementById('qs-input-' + selectId);
    const drop = document.getElementById('qs-drop-' + selectId);
    const clearBtn = document.getElementById('qs-clear-' + selectId);
    if (!sel || !input || !drop) return;

    let activeIdx = -1;
    let filtered = [];

    function getOptions() {
        return Array.from(sel.options)
            .filter(o => o.value !== '')
            .map(o => ({ value: o.value, text: o.text.trim() }));
    }

    function highlight(items) {
        items.forEach((el, i) => {
            el.classList.toggle('qs-active', i === activeIdx);
            if (i === activeIdx) el.scrollIntoView({ block: 'nearest' });
        });
    }

    function renderDrop(opts) {
        filtered = opts;
        activeIdx = opts.length > 0 ? 0 : -1;
        drop.innerHTML = '';
        if (opts.length === 0) {
            drop.innerHTML = '<div class="qs-empty">No results found</div>';
        } else {
            opts.forEach((opt, i) => {
                const div = document.createElement('div');
                div.className = 'qs-item' + (i === 0 ? ' qs-active' : '');
                div.textContent = opt.text;
                div.addEventListener('mousedown', e => { e.preventDefault(); pick(opt); });
                div.addEventListener('mouseover', () => {
                    activeIdx = i;
                    highlight(drop.querySelectorAll('.qs-item'));
                });
                drop.appendChild(div);
            });
        }
        drop.style.display = 'block';
    }

    function pick(opt) {
        sel.value = opt.value;
        input.value = opt.text;
        drop.style.display = 'none';
        if (clearBtn) clearBtn.style.display = 'inline-block';
        activeIdx = -1;
        input.blur();
    }

    input.addEventListener('focus', () => {
        input.value ? renderDrop(getOptions().filter(o => o.text.toLowerCase().includes(input.value.toLowerCase()))) : renderDrop(getOptions());
    });

    input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        if (!q) { sel.value = ''; if (clearBtn) clearBtn.style.display = 'none'; }
        renderDrop(getOptions().filter(o => o.text.toLowerCase().includes(q)));
    });

    input.addEventListener('keydown', e => {
        const items = drop.querySelectorAll('.qs-item');
        if (drop.style.display === 'none') {
            if (e.key === 'ArrowDown' || e.key === 'Enter') { e.preventDefault(); renderDrop(getOptions()); }
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIdx = Math.min(activeIdx + 1, filtered.length - 1);
            highlight(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIdx = Math.max(activeIdx - 1, 0);
            highlight(items);
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            if (activeIdx >= 0 && filtered[activeIdx]) {
                e.preventDefault();
                pick(filtered[activeIdx]);
            }
        } else if (e.key === 'Escape') {
            drop.style.display = 'none';
            activeIdx = -1;
        }
    });

    document.addEventListener('mousedown', e => {
        const wrap = document.getElementById('qs-wrap-' + selectId);
        if (wrap && !wrap.contains(e.target)) drop.style.display = 'none';
    });
}
window.initQuickSelect = initQuickSelect;

window.qsClear = function(selectId) {
    const sel = document.getElementById(selectId);
    const input = document.getElementById('qs-input-' + selectId);
    const btn = document.getElementById('qs-clear-' + selectId);
    const drop = document.getElementById('qs-drop-' + selectId);
    if (sel) sel.value = '';
    if (input) input.value = '';
    if (btn) btn.style.display = 'none';
    if (drop) drop.style.display = 'none';
    input && input.focus();
};

window.qsReset = function(selectId) {
    window.qsClear(selectId);
};

/**
 * ══════════════════════════════════════════════════════════════════════
 * 4. MASTER MODAL HANDLER
 * ══════════════════════════════════════════════════════════════════════
 */
let masterOriginalParent = null;
let masterOriginalNextSibling = null;
let quickAddFocusTrap = null;

function openMasterAddModal(masterType, selectId, title, fieldName) {
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

    const masterModalEl = document.getElementById('masterAddModal');
    const quickModalEl = document.getElementById('quickAddModal');
    const showMasterOverlay = () => {
        if (!masterOriginalParent) {
            masterOriginalParent = masterModalEl.parentNode;
            masterOriginalNextSibling = masterModalEl.nextSibling;
        }
        if (masterModalEl.parentNode !== quickModalEl) {
            quickModalEl.appendChild(masterModalEl);
        }
        const quickModalInstance = bootstrap.Modal.getInstance(quickModalEl);
        if (quickModalInstance && quickModalInstance._focustrap) {
            quickAddFocusTrap = quickModalInstance._focustrap;
            quickAddFocusTrap.deactivate();
        }
        masterModalEl.style.display = 'block';
        masterModalEl.style.setProperty('z-index', '1200', 'important');
        masterModalEl.setAttribute('aria-hidden', 'false');
        masterModalEl.classList.add('show');
        document.body.classList.add('modal-open');
        document.getElementById('masterAddValue').focus();
    };

    if (selectId.indexOf('quick') === 0 && !quickModalEl.classList.contains('show')) {
        bootstrap.Modal.getOrCreateInstance(quickModalEl).show();
        setTimeout(showMasterOverlay, 180);
    } else {
        showMasterOverlay();
    }
}
window.openMasterAddModal = openMasterAddModal;

window.closeMasterAddModal = function() {
    const masterModalEl = document.getElementById('masterAddModal');
    masterModalEl.classList.remove('show');
    masterModalEl.style.display = 'none';
    masterModalEl.setAttribute('aria-hidden', 'true');
    if (masterOriginalParent) {
        masterOriginalParent.insertBefore(masterModalEl, masterOriginalNextSibling);
        masterOriginalParent = null;
        masterOriginalNextSibling = null;
    }
    if (quickAddFocusTrap) {
        quickAddFocusTrap.activate();
        quickAddFocusTrap = null;
    }
    if (document.getElementById('quickAddModal').classList.contains('show')) {
        document.body.classList.add('modal-open');
    }
};

async function submitMasterAdd() {
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
    formData.append('csrfmiddlewaretoken', getCsrfToken());

    if (masterType === 'product-tax') {
        formData.append('tax_rate', extraValue || value);
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
            headers: { 
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': getCsrfToken()
            },
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
            const option = new Option(data.name, data.id, true, true);
            selectEl.add(option);
            selectEl.value = String(data.id);
            
            const visualInput = document.getElementById('qs-input-' + actualSelectId);
            if (visualInput) visualInput.value = data.name;
            const clearBtn = document.getElementById('qs-clear-' + actualSelectId);
            if (clearBtn) clearBtn.style.display = 'inline-block';
            selectEl.dispatchEvent(new Event('change', { bubbles: true }));
        }

        closeMasterAddModal();
        if (selectId.indexOf('quick') === 0) {
            document.getElementById('quickName')?.focus();
        }
        showToast(`${data.name} added successfully`);
    } catch (err) {
        showToast(err.message || 'Save failed', 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-save me-1"></i> Save';
    }
}
window.submitMasterAdd = submitMasterAdd;

/**
 * ══════════════════════════════════════════════════════════════════════
 * 5. CALCULATIONS & GST ENGINE
 * ══════════════════════════════════════════════════════════════════════
 */
function updateUnitPreview() {
    if (!selectedProduct) { document.getElementById('unitPreview').innerText = ''; return; }
    let qty = parseFloat(document.getElementById('itemQty').value) || 0;
    let free = parseFloat(document.getElementById('itemFreeQty').value) || 0;
    let units = (qty + free) * (selectedProduct.conversion_factor || 1);
    document.getElementById('unitPreview').innerHTML = `<i class="fas fa-cubes"></i> Total units: ${units} units`;
    updateItemTotal();
}
window.updateUnitPreview = updateUnitPreview;

function updateItemTotal() {
    const qty = parseFloat(document.getElementById('itemQty').value) || 0;
    const price = parseFloat(document.getElementById('itemPrice').value) || 0;
    const taxPct = parseFloat(document.getElementById('itemTax').value) || 0;
    const discPct = parseFloat(document.getElementById('itemDisc').value) || 0;
    const subTotal = qty * price;
    const discAmt = (subTotal * discPct) / 100;
    const taxable = subTotal - discAmt;

    const amountEl = document.getElementById('itemAmount');
    if (amountEl) amountEl.value = taxable.toFixed(2);

    const el = document.getElementById('itemTotalDisplay');
    if (!el) return;
    const taxAmt = (taxable * taxPct) / 100;
    const total = taxable + taxAmt;
    el.textContent = '₹' + total.toFixed(2);
    if (total > 0) {
        el.style.borderColor = '#16a34a';
        el.style.color = '#15803d';
    } else {
        el.style.borderColor = '#22c55e';
        el.style.color = '#1a7a4a';
    }
}
window.updateItemTotal = updateItemTotal;

function calculateDiscount(changed) {
    const sub = items.reduce((s, i) => {
        const qty = parseFloat(i.quantity) || 0;
        const price = parseFloat(i.purchase_price) || 0;
        const itemDisc = parseFloat(i.discount_percentage) || 0;
        const itemSub = qty * price;
        const itemDiscAmt = (itemSub * itemDisc) / 100;
        return s + (itemSub - itemDiscAmt);
    }, 0);

    let discAmt = parseFloat(document.getElementById('summaryDiscount').value) || 0;
    let discPerc = parseFloat(document.getElementById('summaryDiscountPerc').value) || 0;

    if (changed === 'perc') {
        discAmt = (sub * discPerc) / 100;
        document.getElementById('summaryDiscount').value = discAmt.toFixed(2);
    } else {
        if (sub > 0) discPerc = (discAmt / sub) * 100;
        document.getElementById('summaryDiscountPerc').value = discPerc.toFixed(2);
    }

    calculateSummary();
}
window.calculateDiscount = calculateDiscount;

function calculateSummary() {
    const roundOffInput = document.getElementById('summaryRoundOff');
    const safeMoney = (value) => Number(Math.round((Number(value) || 0) * 100) / 100);
    const toCents = (value) => Math.round((Number(value) || 0) * 100);
    const sumMoney = (values) => values.reduce((total, value) => total + toCents(value), 0) / 100;

    const manualRoundOff = roundOffInput ? (parseFloat(roundOffInput.value) || 0) : 0;

    const originalSub = items.reduce((s, i) => {
        const qty = parseFloat(i.quantity) || 0;
        const price = parseFloat(i.purchase_price) || 0;
        const itemDisc = parseFloat(i.discount_percentage) || 0;
        const itemSub = safeMoney(qty * price);
        const itemDiscAmt = safeMoney((itemSub * itemDisc) / 100);
        return safeMoney(s + (itemSub - itemDiscAmt));
    }, 0);

    const taxSum = sumMoney(items.map(i => parseFloat(i.tax_amount) || 0));

    let discAmt = parseFloat(document.getElementById('summaryDiscount').value) || 0;
    let discPerc = parseFloat(document.getElementById('summaryDiscountPerc').value) || 0;

    const discountRatio = originalSub > 0 ? discAmt / originalSub : 0;
    const effectiveSub = safeMoney(originalSub * (1 - discountRatio));
    const effectiveTax = safeMoney(taxSum * (1 - discountRatio));

    const gstMap = {};
    items.forEach(i => {
        const rate = parseFloat(i.tax_percentage) || 0;
        const adjustedTax = safeMoney((parseFloat(i.tax_amount) || 0) * (1 - discountRatio));
        const cgst = safeMoney(adjustedTax / 2);
        const sgst = safeMoney(adjustedTax / 2);

        if (!gstMap[rate]) gstMap[rate] = { total: 0, cgst: 0, sgst: 0 };
        gstMap[rate].total += adjustedTax;
        gstMap[rate].cgst += cgst;
        gstMap[rate].sgst += sgst;
    });

    const gstDiv = document.getElementById('gstBifurcationSection');
    if (Object.keys(gstMap).length === 0) {
        gstDiv.innerHTML = '';
    } else {
        let html = '';
        Object.keys(gstMap).sort((a, b) => parseFloat(a) - parseFloat(b)).forEach(rate => {
            const g = gstMap[rate];
            g.total = safeMoney(g.total);
            g.cgst = safeMoney(g.total / 2);
            g.sgst = safeMoney(g.total - g.cgst);
            const cgstR = parseFloat(rate) / 2;
            const sgstR = parseFloat(rate) / 2;
            html += `
            <div style="background:#f8f9ff; border-radius:8px; padding:6px 10px; margin-bottom:6px; border-left:3px solid #6366f1;">
                <div class="d-flex justify-content-between fw-semibold" style="font-size:0.78rem; color:#4338ca;">
                    <span>GST @ ${rate}%</span>
                    <span>₹${Number(g.total).toFixed(2)}</span>
                </div>
                <div class="d-flex justify-content-between" style="font-size:0.72rem; color:#6b7280; padding-left:8px;">
                    <span>CGST @ ${cgstR}%</span>
                    <span>₹${Number(g.cgst).toFixed(2)}</span>
                </div>
                <div class="d-flex justify-content-between" style="font-size:0.72rem; color:#6b7280; padding-left:8px;">
                    <span>SGST @ ${sgstR}%</span>
                    <span>₹${Number(g.sgst).toFixed(2)}</span>
                </div>
            </div>`;
        });
        gstDiv.innerHTML = html;
    }

    const grandRaw = safeMoney(effectiveSub + effectiveTax + manualRoundOff);
    const grandRounded = safeMoney(grandRaw);

    document.getElementById('summarySubTotal').innerHTML = `₹${Number(originalSub).toFixed(2)}`;
    document.getElementById('summaryTax').innerHTML = `₹${Number(effectiveTax).toFixed(2)}`;
    document.getElementById('summaryGrandTotal').innerHTML = `₹${grandRounded.toFixed(2)}`;

    const roundOff = safeMoney(grandRounded - (effectiveSub + effectiveTax));
    const roundOffRow = document.getElementById('roundOffRow');
    if (roundOffRow) {
        roundOffRow.style.display = 'flex';
        const roundOffSign = document.getElementById('roundOffSign');
        if (roundOffSign) {
            roundOffSign.textContent = roundOff > 0 ? '(increase)' : roundOff < 0 ? '(decrease)' : '';
            roundOffSign.className = `ms-1 small ${roundOff < 0 ? 'text-danger' : 'text-success'}`;
        }
    }
}
window.calculateSummary = calculateSummary;

/**
 * ══════════════════════════════════════════════════════════════════════
 * 6. TABLE & ITEM ADD/REMOVE ENGINE
 * ══════════════════════════════════════════════════════════════════════
 */
async function addItem() {
    if (!selectedProduct) { 
        showToast('Please select a product from search', 'error'); 
        return; 
    }
    
    const batch = document.getElementById('itemBatch').value.trim().toUpperCase();
    let expiry = document.getElementById('itemExpiry').value;
    const qty = parseFloat(document.getElementById('itemQty').value) || 0;
    const freeQty = parseFloat(document.getElementById('itemFreeQty').value) || 0;
    const price = parseFloat(document.getElementById('itemPrice').value);
    const taxPerc = parseFloat(document.getElementById('itemTax').value) || 0;
    const discPerc = parseFloat(document.getElementById('itemDisc').value) || 0;
    let mrp = parseFloat(document.getElementById('itemMrp').value);

    if (!batch) { showToast('Batch number required', 'error'); return; }

    const isAyurvedic = selectedProduct && selectedProduct.schedule_name && selectedProduct.schedule_name.toUpperCase().trim() === 'AYURVEDIC';
    if (!expiry) {
        if (isAyurvedic) {
            expiry = '2099-12';
        } else {
            showToast('Expiry required', 'error');
            return;
        }
    }

    if (qty <= 0 && freeQty <= 0) {
        showToast('Either Qty or Free quantity must be greater than 0', 'error');
        return;
    }
    if (isNaN(price) || price <= 0) { 
        showToast('Valid cost price required', 'error'); 
        return; 
    }
    if (isNaN(mrp) || mrp <= 0) mrp = price * 1.2;

    const subTotal = qty * price;
    const discAmount = (subTotal * discPerc) / 100;
    const taxable = subTotal - discAmount;
    const taxAmount = Math.round(((taxable * taxPerc) / 100) * 100) / 100;
    const totalWithTax = Math.round((taxable + taxAmount) * 100) / 100;
    const totalUnits = (qty + freeQty) * (selectedProduct.conversion_factor || 1);

    items.push({
        product_id: selectedProduct.id, 
        name: selectedProduct.name, 
        packing: selectedProduct.packing || '',
        schedule_name: selectedProduct.schedule_name || '',
        batch_number: batch, 
        expiry_date: expiry + "-01", 
        quantity: qty, 
        free_quantity: freeQty,
        total_units: totalUnits, 
        purchase_price: price, 
        tax_percentage: taxPerc, 
        discount_percentage: discPerc,
        tax_amount: taxAmount,
        mrp: mrp, 
        sale_price: mrp / (selectedProduct.conversion_factor || 1), 
        total: totalWithTax
    });

    const addedProdName = selectedProduct ? selectedProduct.name : 'Item';
    renderTable();
    resetAddForm();
    showToast(`${addedProdName} added (Batch: ${batch})`);
}
window.addItem = addItem;

function resetAddForm() {
    document.getElementById('itemBatch').value = '';
    document.getElementById('itemExpiry').value = '';
    const expiryFormat = window.EP_CONFIG?.expiryFormat || 'text';
    if (expiryFormat === 'dropdown') {
        document.getElementById('itemExpiryMonth').value = '';
        document.getElementById('itemExpiryYear').value = '';
        document.getElementById('itemExpiryMonth').classList.remove('is-invalid');
        document.getElementById('itemExpiryYear').classList.remove('is-invalid');
    } else {
        const expInput = document.getElementById('itemExpiryInput');
        if (expInput) {
            expInput.value = '';
            expInput.classList.remove('is-invalid');
        }
    }
    document.getElementById('expiryHint').style.display = 'none';
    document.getElementById('itemQty').value = '1';
    document.getElementById('itemFreeQty').value = '0';
    document.getElementById('itemPrice').value = '';
    document.getElementById('itemDisc').value = '0';
    document.getElementById('itemAmount').value = '0.00';
    document.getElementById('itemMrp').value = '';
    document.getElementById('productInfo').style.display = 'none';
    document.getElementById('unitPreview').innerHTML = '';
    selectedProduct = null;
    document.getElementById('productSearch').value = '';
    document.getElementById('itemTax').value = '0';
    hideInlinePrevPurchases();
    const suggestionsDiv = document.getElementById('batchSuggestions');
    suggestionsDiv.innerHTML = '';
    suggestionsDiv.classList.remove('show');
    currentBatchHistory = [];
    const totalDisp = document.getElementById('itemTotalDisplay');
    if (totalDisp) { totalDisp.textContent = '₹0.00'; totalDisp.style.borderColor='#22c55e'; totalDisp.style.color='#1a7a4a'; }
    document.getElementById('productSearch').focus();
}
window.resetAddForm = resetAddForm;

function renderTable() {
    const tbody = document.getElementById('itemsTbody');
    document.getElementById('itemCount').innerText = `${items.length} item${items.length !== 1 ? 's' : ''}`;
    if (items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="13"><div class="empty-state text-center p-4">No items added.</div></td></tr>`;
        calculateSummary();
        return;
    }
    tbody.innerHTML = '';
    items.forEach((item, idx) => {
        let expiryShort = '—';
        if (item.expiry_date) {
            const exp = String(item.expiry_date);
            expiryShort = exp.length >= 7 ? exp.substring(0, 7) : exp;
        }
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${item.name}</strong><div class="small text-muted">${item.packing || ''}</div></td>
            <td><span class="badge-batch">${item.batch_number || '—'}</span></td>
            <td>${expiryShort}</td>
            <td>${item.quantity}</td><td class="text-success">+${item.free_quantity || 0}</td>
            <td>${item.tax_percentage || 0}%</td>
            <td>₹${(item.purchase_price || 0).toFixed(2)}</td>
            <td>${item.discount_percentage || 0}%</td>
            <td>₹${((item.quantity * item.purchase_price) * (1 - (item.discount_percentage || 0) / 100)).toFixed(2)}</td>
            <td>₹${(item.mrp || 0).toFixed(2)}</td>
            <td>₹${(item.tax_amount || 0).toFixed(2)}</td>
            <td>₹${(item.total || 0).toFixed(2)}</td>
            <td class="d-flex gap-1">
                <button class="btn-edit-item" onclick="openEditModal(${idx})" title="Edit"><i class="fas fa-pencil-alt"></i></button>
                <button class="btn-remove" onclick="removeItem(${idx})"><i class="fas fa-trash-alt"></i></button>
            </td>
        `;
        tbody.appendChild(tr);
    });
    calculateSummary();
    savePurchaseDraft();
}
window.renderTable = renderTable;

function removeItem(index) {
    items.splice(index, 1);
    renderTable();
    showToast('Item removed');
}
window.removeItem = removeItem;

/**
 * ══════════════════════════════════════════════════════════════════════
 * 7. BATCH & PREVIOUS PURCHASES ENGINE
 * ══════════════════════════════════════════════════════════════════════
 */
async function fetchBatchHistory(productId) {
    const suggestionsDiv = document.getElementById('batchSuggestions');
    suggestionsDiv.innerHTML = '<div class="history-loading"><i class="fas fa-spinner fa-spin"></i> Loading batches...</div>';
    suggestionsDiv.classList.add('show');
    try {
        const response = await fetch(`/api/products/batch-history/?product_id=${productId}`);
        if (!response.ok) throw new Error('API not ready');
        const data = await response.json();
        currentBatchHistory = data;
        renderBatchSuggestions(data);
    } catch (err) {
        console.warn("Batch history API fallback");
        currentBatchHistory = [];
        renderBatchSuggestions([]);
    }
}

function renderBatchSuggestions(batches) {
    const container = document.getElementById('batchSuggestions');
    batchSelectedIndex = -1;
    if (!batches || batches.length === 0) {
        container.innerHTML = '<div class="p-2 text-muted small">No previous batches found. You can type new batch.</div>';
        return;
    }
    container.innerHTML = '';
    batches.forEach(batch => {
        const div = document.createElement('div');
        div.className = 'batch-suggestion-item';
        const expiryShort = batch.expiry_date ? batch.expiry_date.substring(0,7) : 'N/A';
        const stockText = (batch.stock_quantity !== undefined && batch.stock_quantity > 0) 
            ? `<span class="batch-stock-badge"><i class="fas fa-boxes"></i> Stock: ${batch.stock_quantity}</span>` 
            : '<span class="batch-stock-badge" style="background:#f3f0fa;">Out of stock</span>';
        div.innerHTML = `<div><strong>${batch.batch_number}</strong> &nbsp; Exp: ${expiryShort} &nbsp; MRP: ₹${batch.mrp?.toFixed(2) || '—'} &nbsp; Cost: ₹${batch.purchase_price?.toFixed(2) || '—'} ${stockText}</div>`;
        div.onclick = (e) => {
            e.stopPropagation();
            document.getElementById('itemBatch').value = batch.batch_number;
            if (batch.expiry_date) {
                let exp = batch.expiry_date.substring(0,7);
                const parts = exp.split('-');
                if (parts.length === 2) {
                    const year = parts[0];
                    const month = parts[1];
                    const expiryFormat = window.EP_CONFIG?.expiryFormat || 'text';
                    if (expiryFormat === 'dropdown') {
                        document.getElementById('itemExpiryMonth').value = month;
                        document.getElementById('itemExpiryYear').value = year;
                    } else {
                        document.getElementById('itemExpiryInput').value = `${month}-${year.slice(-2)}`;
                    }
                    document.getElementById('itemExpiry').value = exp;
                    syncExpiryHidden();
                }
            }
            if (batch.mrp) document.getElementById('itemMrp').value = batch.mrp;
            if (batch.purchase_price) document.getElementById('itemPrice').value = batch.purchase_price;
            showToast(`Batch ${batch.batch_number} loaded`, 'success');
            container.classList.remove('show');
        };
        container.appendChild(div);
    });
    container.classList.add('show');
}

function updateBatchSelection() {
    const container = document.getElementById('batchSuggestions');
    const items = container.querySelectorAll('.batch-suggestion-item');
    items.forEach((el, idx) => {
        if (idx === batchSelectedIndex) {
            el.classList.add('selected-item');
            el.scrollIntoView({ block: 'nearest' });
        } else {
            el.classList.remove('selected-item');
        }
    });
}

function updateSearchSelection() {
    const container = document.getElementById('searchResults');
    const items = container.querySelectorAll('button.search-item');
    items.forEach((el, idx) => {
        if (idx === searchSelectedIndex) {
            el.classList.add('selected-item');
            el.scrollIntoView({ block: 'nearest' });
        } else {
            el.classList.remove('selected-item');
        }
    });
}

async function openPreviousPurchases(productId, productName) {
    document.getElementById('purchasesModalProductName').textContent = productName;
    const tbody = document.querySelector('#previousPurchasesTable tbody');
    tbody.innerHTML = '<tr><td colspan="10" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin"></i> Loading last purchases...</td></tr>';
    
    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('previousPurchasesModal'));
    modal.show();

    try {
        const resp = await fetch(`/product-history/?product_id=${productId}&ajax=1`, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const data = await resp.json();
        tbody.innerHTML = '';
        
        if (!data.purchases || data.purchases.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" class="text-center py-4 text-muted">No purchase entries recorded for this medicine.</td></tr>';
        } else {
            data.purchases.slice(0, 7).forEach(p => {
                const row = document.createElement('tr');
                const mrpVal = (p.mrp !== undefined && p.mrp !== null) ? `₹${parseFloat(p.mrp).toFixed(2)}` : '-';
                row.innerHTML = `
                    <td>${p.date}</td>
                    <td><span class="badge bg-light text-dark border">${p.invoice_number}</span></td>
                    <td class="fw-bold text-dark">${p.supplier_name}</td>
                    <td><span class="badge bg-light text-secondary border">${p.batch_number}</span></td>
                    <td>${p.expiry_date}</td>
                    <td class="fw-bold">${p.quantity}</td>
                    <td class="text-success">+${p.free_quantity}</td>
                    <td class="fw-bold">₹${p.purchase_price.toFixed(2)}</td>
                    <td class="fw-bold text-secondary">${mrpVal}</td>
                    <td class="text-end fw-bold text-primary">₹${p.total.toFixed(2)}</td>
                `;
                tbody.appendChild(row);
            });
        }
    } catch (error) {
        tbody.innerHTML = '<tr><td colspan="10" class="text-center py-4 text-danger">Error loading purchases</td></tr>';
    }
}
window.openPreviousPurchases = openPreviousPurchases;

async function loadInlinePreviousPurchases(productId, productName) {
    const panel = document.getElementById('inlinePrevPurchases');
    const tbody = document.querySelector('#inlinePrevPurchasesTable tbody');
    document.getElementById('prevPurchaseProductName').textContent = productName;

    panel.style.display = 'block';
    tbody.innerHTML = '<tr><td colspan="10" class="text-center py-3 text-muted"><i class="fas fa-spinner fa-spin"></i> Loading previous purchases...</td></tr>';

    try {
        const resp = await fetch(`/product-history/?product_id=${productId}&ajax=1`, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const data = await resp.json();
        tbody.innerHTML = '';

        if (!data.purchases || data.purchases.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" class="text-center py-3 text-muted">No previous purchase entries for this medicine.</td></tr>';
            return;
        }

        data.purchases.slice(0, 5).forEach(p => {
            const row = document.createElement('tr');
            const mrpVal = (p.mrp !== undefined && p.mrp !== null) ? `₹${parseFloat(p.mrp).toFixed(2)}` : '-';
            row.innerHTML = `
                <td>${p.date}</td>
                <td><span class="badge bg-light text-dark border">${p.invoice_number}</span></td>
                <td class="fw-bold text-dark">${p.supplier_name}</td>
                <td><span class="badge bg-light text-secondary border">${p.batch_number}</span></td>
                <td>${p.expiry_date}</td>
                <td class="fw-bold">${p.quantity}</td>
                <td class="text-success">+${p.free_quantity}</td>
                <td class="fw-bold">₹${p.purchase_price.toFixed(2)}</td>
                <td class="fw-bold text-secondary">${mrpVal}</td>
                <td class="text-end fw-bold text-primary">₹${p.total.toFixed(2)}</td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        tbody.innerHTML = '<tr><td colspan="10" class="text-center py-3 text-danger">Error loading previous purchases</td></tr>';
    }
}
window.loadInlinePreviousPurchases = loadInlinePreviousPurchases;

function hideInlinePrevPurchases() {
    const panel = document.getElementById('inlinePrevPurchases');
    if (panel) panel.style.display = 'none';
}
window.hideInlinePrevPurchases = hideInlinePrevPurchases;

/**
 * ══════════════════════════════════════════════════════════════════════
 * 8. DRAFT SAVING & RECOVERY
 * ══════════════════════════════════════════════════════════════════════
 */
function savePurchaseDraft() {
    if (window.EP_CONFIG?.editData) return;
    try {
        const hasData = (items && items.length > 0) || 
                        Boolean(document.getElementById('invoiceNumber')?.value?.trim()) || 
                        Boolean(document.getElementById('supplierSelect')?.value);
        if (hasData) {
            const draft = {
                supplier_id: document.getElementById('supplierSelect')?.value || '',
                supplier_name: document.getElementById('supplierSearchInput')?.value || '',
                invoice_number: document.getElementById('invoiceNumber')?.value || '',
                purchase_date: document.getElementById('purchaseDate')?.value || '',
                discount_percentage: document.getElementById('summaryDiscountPerc')?.value || '0',
                discount_amount: document.getElementById('summaryDiscount')?.value || '0',
                payment_mode: document.getElementById('summaryPaymentMode')?.value || 'Cash',
                items: items,
                timestamp: Date.now()
            };
            localStorage.setItem('easypharma_purchase_draft_v1', JSON.stringify(draft));
        } else {
            localStorage.removeItem('easypharma_purchase_draft_v1');
        }
    } catch (e) {}
}
window.savePurchaseDraft = savePurchaseDraft;

function clearPurchaseDraft() {
    try { localStorage.removeItem('easypharma_purchase_draft_v1'); } catch (e) {}
}
window.clearPurchaseDraft = clearPurchaseDraft;

function restorePurchaseDraft() {
    if (window.EP_CONFIG?.editData) return;
    try {
        const raw = localStorage.getItem('easypharma_purchase_draft_v1');
        if (!raw) return;
        const draft = JSON.parse(raw);
        if (draft && (Array.isArray(draft.items) && draft.items.length > 0 || draft.invoice_number || draft.supplier_id)) {
            if (draft.supplier_id && document.getElementById('supplierSelect')) {
                document.getElementById('supplierSelect').value = draft.supplier_id;
            }
            if (draft.supplier_name && document.getElementById('supplierSearchInput')) {
                document.getElementById('supplierSearchInput').value = draft.supplier_name;
            }
            if (draft.invoice_number && document.getElementById('invoiceNumber')) {
                document.getElementById('invoiceNumber').value = draft.invoice_number;
            }
            if (draft.purchase_date && document.getElementById('purchaseDate')) {
                document.getElementById('purchaseDate').value = draft.purchase_date;
            }
            if (draft.discount_percentage && document.getElementById('summaryDiscountPerc')) {
                document.getElementById('summaryDiscountPerc').value = draft.discount_percentage;
            }
            if (draft.discount_amount && document.getElementById('summaryDiscount')) {
                document.getElementById('summaryDiscount').value = draft.discount_amount;
            }
            if (draft.payment_mode && document.getElementById('summaryPaymentMode')) {
                document.getElementById('summaryPaymentMode').value = draft.payment_mode;
            }
            if (Array.isArray(draft.items) && draft.items.length > 0) {
                items = draft.items;
                renderTable();
            } else {
                calculateSummary();
            }
            showToast('⚡ Restored unsaved purchase from previous session! <button type="button" class="btn btn-sm btn-outline-light ms-2" onclick="clearPurchaseDraftAndReset()" style="padding:1px 6px;font-size:11px;">Clear Draft</button>', 'success');
        }
    } catch (e) {}
}

window.clearPurchaseDraftAndReset = function() {
    clearPurchaseDraft();
    items = [];
    if (document.getElementById('invoiceNumber')) document.getElementById('invoiceNumber').value = '';
    if (document.getElementById('supplierSelect')) document.getElementById('supplierSelect').value = '';
    if (document.getElementById('supplierSearchInput')) document.getElementById('supplierSearchInput').value = '';
    if (document.getElementById('summaryDiscount')) document.getElementById('summaryDiscount').value = '0';
    if (document.getElementById('summaryDiscountPerc')) document.getElementById('summaryDiscountPerc').value = '0';
    renderTable();
    showToast('Draft cleared', 'error');
};

/**
 * ══════════════════════════════════════════════════════════════════════
 * LIVE DUPLICATE INVOICE VERIFICATION
 * ══════════════════════════════════════════════════════════════════════
 */
let duplicateInvoiceExists = false;
let checkInvoiceTimeout = null;

async function checkDuplicateInvoice(showToastNotification = true) {
    const suppSelect = document.getElementById('supplierSelect');
    const suppInput = document.getElementById('supplierSearchInput');
    const invInput = document.getElementById('invoiceNumber');
    const warnBox = document.getElementById('duplicateInvoiceWarning');
    const warnText = document.getElementById('duplicateInvoiceText');
    const spinner = document.getElementById('invoiceCheckSpinner');

    if (!invInput) return;

    let supplier_id = suppSelect ? suppSelect.value : '';
    // If supplierSelect is empty but user typed or selected in searchInput, resolve it
    if (!supplier_id && suppInput && suppInput.value.trim() && suppSelect) {
        const rawText = suppInput.value.trim().toLowerCase();
        const opt = Array.from(suppSelect.options).find(o => 
            o.value && (
                o.text.toLowerCase().split(' | ')[0].trim() === rawText ||
                o.text.toLowerCase().startsWith(rawText) ||
                rawText.startsWith(o.text.toLowerCase().split(' | ')[0].trim())
            )
        );
        if (opt) {
            supplier_id = opt.value;
            suppSelect.value = opt.value;
        }
    }

    const invoice_number = invInput.value.trim();
    const editId = window.EP_CONFIG?.editData?.id || '';

    if (!invoice_number) {
        duplicateInvoiceExists = false;
        if (warnBox) warnBox.classList.add('d-none');
        if (spinner) spinner.classList.add('d-none');
        invInput.classList.remove('is-invalid');
        return;
    }

    if (spinner) spinner.classList.remove('d-none');

    try {
        let url = `/purchase/check-invoice-number/?invoice_number=${encodeURIComponent(invoice_number)}`;
        if (supplier_id) url += `&supplier_id=${encodeURIComponent(supplier_id)}`;
        if (editId) url += `&invoice_id=${encodeURIComponent(editId)}`;

        const resp = await fetch(url, { silent: true });
        const res = await resp.json();

        if (res.exists) {
            duplicateInvoiceExists = true;
            const sName = res.supplier_name || 'this supplier';
            const vNum = res.voucher_number ? ` (Voucher: ${res.voucher_number})` : '';
            const pDate = res.purchase_date ? ` dated ${res.purchase_date}` : '';
            const pAmt = res.total_amount ? ` for ₹${Number(res.total_amount).toLocaleString('en-IN', {minimumFractionDigits: 2})}` : '';
            const msg = `Invoice #${res.invoice_number || invoice_number} already exists for ${sName}${vNum}${pDate}${pAmt}! Duplicate entries are not allowed.`;

            if (warnBox) {
                if (warnText) warnText.textContent = msg;
                warnBox.classList.remove('d-none');
            }
            invInput.classList.add('is-invalid');

            if (showToastNotification) {
                showToast(msg, 'error');
            }
        } else {
            duplicateInvoiceExists = false;
            if (warnBox) warnBox.classList.add('d-none');
            invInput.classList.remove('is-invalid');
        }
    } catch (err) {
        console.error('Invoice check failed:', err);
    } finally {
        if (spinner) spinner.classList.add('d-none');
    }
}
window.checkDuplicateInvoice = checkDuplicateInvoice;

function debouncedCheckDuplicateInvoice(showToastNotification = true) {
    clearTimeout(checkInvoiceTimeout);
    checkInvoiceTimeout = setTimeout(() => {
        checkDuplicateInvoice(showToastNotification);
    }, 250);
}

/**
 * ══════════════════════════════════════════════════════════════════════
 * 9. SAVE PURCHASE & ONLINE/OFFLINE ENGINE
 * ══════════════════════════════════════════════════════════════════════
 */
async function savePurchase() {
    const supplier = document.getElementById('supplierSelect').value;
    const invNo = document.getElementById('invoiceNumber').value.trim();

    if (!supplier) return showToast('Select supplier', 'error');
    if (!invNo) return showToast('Enter invoice number', 'error');

    // Prevent saving duplicate invoice
    if (duplicateInvoiceExists) {
        const warnText = document.getElementById('duplicateInvoiceText')?.textContent;
        showToast(warnText || `Invoice #${invNo} already exists for this supplier!`, 'error');
        const invInput = document.getElementById('invoiceNumber');
        if (invInput) {
            invInput.focus();
            invInput.select();
        }
        return;
    }

    if (items.length === 0) return showToast('Add at least one item', 'error');

    const saveBtn = document.querySelector('.btn-complete');
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.classList.add('disabled');
    }
    showLoader('Saving purchase...');

    const applied_returns = [];
    document.querySelectorAll('.cn-checkbox').forEach((chk) => {
        if (chk.checked) {
            const idx = chk.dataset.idx;
            const amt = parseFloat(document.getElementById(`cn-amt-${idx}`).value) || 0;
            if (amt > 0 && availableCreditNotes[idx]) {
                applied_returns.push({
                    return_id: availableCreditNotes[idx].id,
                    amount: amt
                });
            }
        }
    });

    const data = {
        supplier_id: parseInt(supplier),
        invoice_number: invNo,
        purchase_date: document.getElementById('purchaseDate').value,
        items: items,
        sub_total: parseFloat(document.getElementById('summarySubTotal').innerText.replace(/[^0-9.-]+/g, '')) || 0,
        tax_amount: parseFloat(document.getElementById('summaryTax').innerText.replace(/[^0-9.-]+/g, '')) || 0,
        discount_percentage: parseFloat(document.getElementById('summaryDiscountPerc').value) || 0,
        discount_amount: parseFloat(document.getElementById('summaryDiscount').value) || 0,
        payment_mode: document.getElementById('summaryPaymentMode').value || 'Cash',
        total_amount: parseFloat(document.getElementById('summaryGrandTotal').innerText.replace(/[^0-9.-]+/g, '')) || 0,
        round_off: parseFloat(document.getElementById('summaryRoundOff').value) || 0,
        applied_returns: applied_returns
    };

    const endpoint = window.location.pathname.endsWith('/') 
        ? window.location.pathname 
        : window.location.pathname + '/';

    try {
        if (!navigator.onLine && typeof OfflineSync !== 'undefined') {
            await OfflineSync.queueRequest(
                OfflineSync.purchaseStore, 
                endpoint, 
                data, 
                'Purchase saved offline! Will sync when online.'
            );
            showPurchaseConfirm({ success: true, purchase_number: 'OFF-' + Date.now() });
        } else {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(data)
            });

            const result = await response.json().catch(() => ({}));

            if (response.ok && (result.success || result.status === 'success')) {
                if (typeof OfflineSync !== 'undefined') {
                    OfflineSync.preloadProductCache();
                }
                showPurchaseConfirm(result);
            } else if (result.queued) {
                showPurchaseConfirm({ success: true, purchase_number: 'SW-OFF-' + Date.now() });
            } else {
                showToast(result.error || 'Server error occurred', 'error');
            }
        }
    } catch (err) {
        if (typeof OfflineSync !== 'undefined') {
            await OfflineSync.queueRequest(OfflineSync.purchaseStore, endpoint, data, 'Purchase saved offline!');
            showPurchaseConfirm({ success: true, purchase_number: 'OFF-' + Date.now() });
        } else {
            showToast('Network error: ' + err.message, 'error');
        }
    } finally {
        hideLoader();
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.classList.remove('disabled');
        }
    }
}
window.savePurchase = savePurchase;

function showPurchaseConfirm(result) {
    let pvNum = 'OFF-' + Date.now();
    if (result && (result.purchase_number || result.voucher_number || result.id)) {
        pvNum = result.purchase_number || result.voucher_number || ('PV-' + result.id);
    }
    document.getElementById('confirmPurchaseNumber').textContent = pvNum;

    let suppName = '—';
    const suppSel = document.getElementById('supplierSelect');
    if (suppSel && suppSel.options && suppSel.selectedIndex >= 0) {
        const optionText = suppSel.options[suppSel.selectedIndex].textContent || '';
        suppName = optionText.split('|')[0].trim();
    }
    document.getElementById('confirmSupplier').textContent = suppName;
    document.getElementById('confirmInvoice').textContent = document.getElementById('invoiceNumber').value || '—';
    document.getElementById('confirmItems').textContent = (items ? items.length : 0) + ' item' + ((items && items.length !== 1) ? 's' : '');
    document.getElementById('confirmTotal').textContent = document.getElementById('summaryGrandTotal').innerText || '₹0.00';

    hideLoader();
    window.__isPurchaseSubmitting = true;
    clearPurchaseDraft();

    const modalElement = document.getElementById('purchaseConfirmModal');
    if (modalElement) {
        const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
        modal.show();
    } else {
        showToast('Purchase saved successfully!', 'success');
    }
}
window.showPurchaseConfirm = showPurchaseConfirm;

/**
 * ══════════════════════════════════════════════════════════════════════
 * 10. EDIT MODAL & MASTER MODAL ACTIONS
 * ══════════════════════════════════════════════════════════════════════
 */
function openEditModal(idx) {
    const item = items[idx];
    if (!item) return;
    document.getElementById('editItemIdx').value = idx;
    document.getElementById('editItemName').value = item.name;
    document.getElementById('editItemBatch').value = item.batch_number || '';
    const exp = String(item.expiry_date || '');
    if (exp.length >= 7) {
        if (exp.substring(0, 7) === '2099-12') {
            document.getElementById('editItemExpiryMonth').value = '';
            document.getElementById('editItemExpiryYear').value = '';
        } else {
            document.getElementById('editItemExpiryMonth').value = exp.substring(5, 7);
            document.getElementById('editItemExpiryYear').value = exp.substring(0, 4);
        }
    } else {
        document.getElementById('editItemExpiryMonth').value = '';
        document.getElementById('editItemExpiryYear').value = '';
    }
    document.getElementById('editItemQty').value = item.quantity;
    document.getElementById('editItemFreeQty').value = item.free_quantity || 0;
    document.getElementById('editItemPrice').value = (item.purchase_price || 0).toFixed(2);
    document.getElementById('editItemMrp').value = (item.mrp || 0).toFixed(2);
    document.getElementById('editItemDisc').value = item.discount_percentage || 0;
    document.getElementById('editItemTax').value = item.tax_percentage || 0;
    const modal = new bootstrap.Modal(document.getElementById('editItemModal'));
    modal.show();
}
window.openEditModal = openEditModal;

function saveEditItem() {
    const idx = parseInt(document.getElementById('editItemIdx').value);
    const item = items[idx];
    if (!item) return;

    const batch = document.getElementById('editItemBatch').value.trim().toUpperCase();
    const em = document.getElementById('editItemExpiryMonth').value;
    const ey = document.getElementById('editItemExpiryYear').value;
    const qty = parseFloat(document.getElementById('editItemQty').value);
    const freeQty = parseFloat(document.getElementById('editItemFreeQty').value) || 0;
    const price = parseFloat(document.getElementById('editItemPrice').value);
    const mrp = parseFloat(document.getElementById('editItemMrp').value);
    const discPerc = parseFloat(document.getElementById('editItemDisc').value) || 0;
    const taxPerc = parseFloat(document.getElementById('editItemTax').value) || 0;

    if (!batch) { showToast('Batch number required', 'error'); return; }
    
    const isAyurvedic = item && item.schedule_name && item.schedule_name.toUpperCase().trim() === 'AYURVEDIC';
    if ((!em || !ey || ey.length < 4) && !isAyurvedic) { showToast('Valid expiry required', 'error'); return; }
    if (isNaN(qty) || qty <= 0) { showToast('Valid quantity required', 'error'); return; }
    if (isNaN(price) || price <= 0) { showToast('Valid cost price required', 'error'); return; }

    let expiry_date = '';
    if (!em || !ey) {
        expiry_date = isAyurvedic ? '2099-12-01' : '';
        if (!expiry_date) { showToast('Valid expiry required', 'error'); return; }
    } else {
        expiry_date = `${ey}-${em}-01`;
    }

    const subTotal = qty * price;
    const discAmount = (subTotal * discPerc) / 100;
    const taxable = subTotal - discAmount;
    const taxAmount = Math.round(((taxable * taxPerc) / 100) * 100) / 100;
    const totalWithTax = Math.round((taxable + taxAmount) * 100) / 100;
    const totalUnits = (qty + freeQty) * (item.conversion_factor || 1);

    items[idx] = {
        ...item,
        batch_number: batch,
        expiry_date: expiry_date,
        quantity: qty,
        free_quantity: freeQty,
        total_units: totalUnits,
        purchase_price: price,
        mrp: isNaN(mrp) ? price * 1.2 : mrp,
        sale_price: (isNaN(mrp) ? price * 1.2 : mrp) / (item.conversion_factor || 1),
        discount_percentage: discPerc,
        tax_amount: taxAmount,
        total: totalWithTax
    };

    renderTable();
    bootstrap.Modal.getInstance(document.getElementById('editItemModal')).hide();
    showToast('Item updated successfully');
}
window.saveEditItem = saveEditItem;

function openEditProductModal() {
    if (!selectedProduct) { showToast('Select a product first', 'error'); return; }
    const p = selectedProduct;

    document.getElementById('editProdId').value = p.id;
    document.getElementById('editProdName').value = p.name;
    document.getElementById('editProdPacking').value = p.packing || '';
    document.getElementById('editProdConv').value = p.conversion_factor || 1;
    document.getElementById('editProdHsn').value = p.hsn_code || '';
    document.getElementById('editProdSubtitle').textContent = 'Editing: ' + p.name;
    document.getElementById('editProdFeedback').style.display = 'none';

    const taxSel = document.getElementById('editProdTax');
    let matched = false;
    Array.from(taxSel.options).forEach(opt => {
        const rate = parseFloat(opt.dataset.rate);
        if (!isNaN(rate) && rate === parseFloat(p.tax_rate)) {
            taxSel.value = opt.value;
            matched = true;
        }
    });
    if (!matched) taxSel.value = '';

    const schedSel = document.getElementById('editProdSchedule');
    schedSel.value = p.schedule_id || '';
    const compSel = document.getElementById('editProdCompany');
    compSel.value = p.company_id || '';

    bootstrap.Modal.getOrCreateInstance(document.getElementById('editProductModal')).show();
}
window.openEditProductModal = openEditProductModal;

function renderSelectedProductBanner(p) {
    const infoContainer = document.getElementById('productInfo');
    if (!infoContainer) return;
    if (!p) {
        infoContainer.style.display = 'none';
        infoContainer.innerHTML = '';
        return;
    }
    const isAyurvedic = p.schedule_name && p.schedule_name.toUpperCase().trim() === 'AYURVEDIC';
    const ayurBadge = isAyurvedic ? '<span class="badge bg-warning text-dark ms-1"><i class="fas fa-leaf me-1"></i>Ayurvedic</span>' : '';

    infoContainer.innerHTML = `
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 p-2" style="background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 8px;">
            <div class="d-flex align-items-center gap-2 flex-wrap">
                <span class="badge bg-success" style="font-size: 0.8rem; font-weight: 600;"><i class="fas fa-check-circle me-1"></i> ${p.name}</span>
                <span class="text-dark fw-bold" style="font-size: 0.8rem;">Packing: <span class="badge bg-light text-dark border">${p.packing || 'Standard'}</span></span>
                <span class="text-dark fw-bold" style="font-size: 0.8rem;">Factor: <span class="badge bg-light text-dark border">×${p.conversion_factor || 1}</span></span>
                <span class="text-dark fw-bold" style="font-size: 0.8rem;">GST: <span class="badge bg-info text-dark">${p.tax_rate !== undefined ? p.tax_rate : 0}%</span></span>
                ${ayurBadge}
                ${p.salt ? `<span class="text-muted fst-italic" style="font-size: 0.76rem;"><i class="fas fa-flask text-warning me-1"></i>${p.salt}</span>` : ''}
            </div>
            <div class="d-flex align-items-center gap-2 ms-auto">
                <button type="button" class="btn btn-warning btn-sm py-1 px-2.5 rounded-pill fw-bold text-dark border-0 shadow-sm" style="font-size: 0.75rem;" onclick="openPreviousPurchases(${p.id}, '${(p.name||'').replace(/'/g,"\\'")}')">
                    <i class="fas fa-history me-1"></i> History
                </button>
                <button type="button" class="btn btn-outline-primary btn-sm py-1 px-2.5 rounded-pill fw-bold" style="font-size:0.75rem; background:white;" onclick="openEditProductModal()">
                    <i class="fas fa-edit me-1"></i> Edit
                </button>
            </div>
        </div>
    `;
    infoContainer.style.display = 'block';
    const taxInput = document.getElementById('itemTax');
    if (taxInput && p.tax_rate !== undefined && p.tax_rate !== null) {
        taxInput.value = p.tax_rate;
    }
    updateUnitPreview();
    updateItemTotal();
}
window.renderSelectedProductBanner = renderSelectedProductBanner;

async function saveEditProduct() {
    const id = document.getElementById('editProdId').value;
    if (!id) return;

    const packing = document.getElementById('editProdPacking').value.trim();
    const conv = parseFloat(document.getElementById('editProdConv').value) || 1;
    const taxId = document.getElementById('editProdTax').value || null;
    const schedId = document.getElementById('editProdSchedule').value || null;
    const compId = document.getElementById('editProdCompany').value || null;
    const hsn = document.getElementById('editProdHsn').value.trim() || null;

    const taxSel = document.getElementById('editProdTax');
    const selOpt = taxSel.options[taxSel.selectedIndex];
    const newTaxRate = selOpt && selOpt.dataset.rate ? parseFloat(selOpt.dataset.rate) : (selectedProduct ? parseFloat(selectedProduct.tax_rate || 0) : 0);

    const saveBtn = document.getElementById('editProdSaveBtn');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Saving...';

    const feedback = document.getElementById('editProdFeedback');

    try {
        const resp = await fetch(`/api/products/quick-add/${id}/`, {
            method: 'PATCH',
            headers: { 
                'Content-Type': 'application/json', 
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                packing,
                conversion_factor: conv,
                tax_id: taxId,
                schedule_id: schedId,
                company_id: compId,
                hsn_code: hsn,
            })
        });
        const res = await resp.json();

        if (!resp.ok || !res.success) {
            feedback.className = 'alert alert-danger py-2';
            feedback.innerHTML = '<i class="fas fa-exclamation-circle me-1"></i>' + (res.error || 'Could not update product');
            feedback.style.display = 'block';
        } else {
            // Update active selectedProduct state immediately
            if (selectedProduct && selectedProduct.id == id) {
                selectedProduct.packing = packing;
                selectedProduct.conversion_factor = conv;
                selectedProduct.hsn_code = hsn;
                selectedProduct.tax_rate = newTaxRate;
                if (schedId) {
                    selectedProduct.schedule_id = schedId;
                    const schedSel = document.getElementById('editProdSchedule');
                    selectedProduct.schedule_name = schedSel.options[schedSel.selectedIndex]?.text || '';
                }
                if (compId) selectedProduct.company_id = compId;

                // Re-render the banner and update input fields immediately
                renderSelectedProductBanner(selectedProduct);
            }

            // Recalculate any items already added to the bill
            let recalcCount = 0;
            items.forEach(item => {
                if (item.product_id == id) {
                    item.packing = packing;
                    item.conversion_factor = conv;
                    item.hsn_code = hsn;
                    item.total_units = (item.quantity + (item.free_quantity || 0)) * conv;
                    item.sale_price = (item.mrp || (item.purchase_price * 1.2)) / conv;
                    if (newTaxRate !== null && newTaxRate !== undefined) {
                        const subTotal = item.quantity * item.purchase_price;
                        const discAmount = (subTotal * (item.discount_percentage || 0)) / 100;
                        const taxable = subTotal - discAmount;
                        item.tax_percentage = newTaxRate;
                        item.tax_amount = Math.round(((taxable * newTaxRate) / 100) * 100) / 100;
                        item.total = Math.round((taxable + item.tax_amount) * 100) / 100;
                    }
                    recalcCount++;
                }
            });
            if (recalcCount > 0) renderTable();

            // Update localforage cache if present
            if (typeof localforage !== 'undefined') {
                try {
                    const store = localforage.createInstance({ name: 'ep_product_cache' });
                    const cached = await store.getItem('master_products');
                    if (Array.isArray(cached)) {
                        const match = cached.find(x => x.id == id);
                        if (match) {
                            match.packing = packing;
                            match.conversion_factor = conv;
                            match.tax_rate = newTaxRate;
                            match.hsn_code = hsn;
                            await store.setItem('master_products', cached);
                        }
                    }
                } catch(e) {}
            }

            showToast(`"${selectedProduct ? selectedProduct.name : 'Product'}" updated instantly!`, 'success');
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
}
window.saveEditProduct = saveEditProduct;

window.saveSupplier = async function() {
    const name = document.getElementById('supplierName').value.trim();
    if (!name) return showToast('Supplier name is required', 'error');

    const payload = new URLSearchParams();
    payload.append('name', name);
    payload.append('phone', document.getElementById('supplierPhone').value.trim());
    payload.append('dl_number', document.getElementById('supplierDl').value.trim());
    payload.append('gst_number', document.getElementById('supplierGst').value.trim());
    payload.append('address', document.getElementById('supplierAddress').value.trim());

    try {
        const resp = await fetch('/type/drug-supplier/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: payload.toString()
        });
        const res = await resp.json();
        if (!res.success) {
            return showToast('Error: ' + (res.error || 'Could not save supplier'), 'error');
        }

        const supplierSelect = document.getElementById('supplierSelect');
        const option = document.createElement('option');
        option.value = res.id;
        option.text = res.name;
        supplierSelect.appendChild(option);
        supplierSelect.value = res.id;
        
        const si = document.getElementById('supplierSearchInput');
        if (si) si.value = res.name;

        ['supplierName', 'supplierPhone', 'supplierAddress', 'supplierGst', 'supplierDl'].forEach(id => document.getElementById(id).value = '');
        bootstrap.Modal.getOrCreateInstance(document.getElementById('supplierModal')).hide();
        showToast(`Supplier "${res.name}" added`);
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
};

window.saveQuickProduct = async function(isOcrMode) {
    const name = document.getElementById('quickName').value.trim();
    if (!name) return showToast('Medicine name is required', 'error');

    const packing = document.getElementById('quickPacking').value.trim() || '1';
    const conv = parseInt(document.getElementById('quickConv').value) || 1;
    const type_id = document.getElementById('quickType').value || null;
    const tax_id = document.getElementById('quickTax').value || null;
    const schedule_id = document.getElementById('quickSchedule').value || null;
    const company_id = document.getElementById('quickCompany').value || null;
    const content_id = document.getElementById('quickContent').value || null;
    const hsn_code = document.getElementById('quickHsn').value.trim() || null;

    // Get Tax Rate value
    const taxSelect = document.getElementById('quickTax');
    let taxRate = 0;
    if (taxSelect && taxSelect.selectedIndex >= 0) {
        const selectedTaxOption = taxSelect.options[taxSelect.selectedIndex];
        if (selectedTaxOption && selectedTaxOption.dataset && selectedTaxOption.dataset.rate) {
            taxRate = parseFloat(selectedTaxOption.dataset.rate) || 0;
        } else if (selectedTaxOption && selectedTaxOption.text) {
            const m = selectedTaxOption.text.match(/(\d+(\.\d+)?)/);
            if (m) taxRate = parseFloat(m[1]) || 0;
        }
    }

    const schedSelect = document.getElementById('quickSchedule');
    const scheduleName = (schedSelect && schedSelect.selectedIndex >= 0) ? schedSelect.options[schedSelect.selectedIndex].text : '';

    const compSelect = document.getElementById('quickCompany');
    const companyName = (compSelect && compSelect.selectedIndex >= 0) ? compSelect.options[compSelect.selectedIndex].text : '';

    const data = {
        name: name,
        packing: packing,
        conversion_factor: conv,
        type_id: type_id,
        tax_id: tax_id,
        schedule_id: schedule_id,
        company_id: company_id,
        content_id: content_id,
        hsn_code: hsn_code,
    };

    const clearQuickAddForm = () => {
        const modalEl = document.getElementById('quickAddModal');
        if (modalEl) {
            const instance = bootstrap.Modal.getInstance(modalEl) || bootstrap.Modal.getOrCreateInstance(modalEl);
            instance.hide();
        }
        ['quickName', 'quickPacking', 'quickHsn'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        const convEl = document.getElementById('quickConv');
        if (convEl) convEl.value = 1;
        ['quickTax', 'quickSchedule', 'quickContent', 'quickCompany', 'quickType'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
            typeof qsClear === 'function' && qsClear(id);
        });
    };

    const applySelectedProductToPurchase = (prod) => {
        selectedProduct = prod;
        const searchInput = document.getElementById('productSearch');
        if (searchInput) searchInput.value = prod.name;
        
        renderSelectedProductBanner(prod);
        
        const searchResultsDiv = document.getElementById('searchResults');
        if (searchResultsDiv) {
            searchResultsDiv.style.display = 'none';
            searchResultsDiv.classList.remove('open');
        }
        const suggestionsDiv = document.getElementById('batchSuggestions');
        if (suggestionsDiv) {
            suggestionsDiv.innerHTML = '';
            suggestionsDiv.classList.remove('show');
        }
        if (prod.id && typeof prod.id === 'number') {
            fetchBatchHistory(prod.id);
            loadInlinePreviousPurchases(prod.id, prod.name);
        }
        const batchInput = document.getElementById('itemBatch');
        if (batchInput) {
            batchInput.focus();
            batchInput.select();
        }
    };

    // Offline Handler
    const handleSaveOffline = async () => {
        const offlineId = 'offline_prod_' + Date.now();
        const offlineProd = {
            id: offlineId,
            name: name,
            product_name: name,
            packing: packing,
            product_packing: packing,
            conversion_factor: conv,
            tax_rate: taxRate,
            tax_id: tax_id,
            schedule_id: schedule_id,
            schedule_name: scheduleName,
            company_id: company_id,
            company_name: companyName,
            content_id: content_id,
            hsn_code: hsn_code,
            is_offline: true,
            batches: []
        };

        if (typeof OfflineSync !== 'undefined') {
            await OfflineSync.cacheNewProduct(offlineProd);
            await OfflineSync.queueRequest(
                OfflineSync.masterStore,
                '/api/products/quick-add/',
                data,
                `Medicine "${name}" saved locally (Offline mode ✓)`
            );
        }

        clearQuickAddForm();
        showToast(`Medicine "${name}" added locally (Offline ✓)`);

        if (!isOcrMode) {
            applySelectedProductToPurchase(offlineProd);
        } else if (typeof onQuickProductSavedOCR === 'function') {
            onQuickProductSavedOCR(offlineProd);
        }
    };

    // If device is offline, directly save locally
    if (!navigator.onLine) {
        await handleSaveOffline();
        return;
    }

    // When online, attempt server POST with automatic offline fallback on network failure
    try {
        const resp = await fetch('/api/products/quick-add/', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json', 
                'X-CSRFToken': getCsrfToken(),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(data)
        });

        const res = await resp.json().catch(() => ({}));
        if (resp.ok && res.success) {
            const onlineProd = {
                id: res.id,
                name: res.name || name,
                product_name: res.name || name,
                packing: packing,
                product_packing: packing,
                conversion_factor: conv,
                tax_rate: res.tax_rate !== undefined && res.tax_rate !== null ? parseFloat(res.tax_rate) : taxRate,
                tax_id: tax_id,
                schedule_id: schedule_id,
                schedule_name: scheduleName,
                company_id: company_id,
                company_name: companyName,
                content_id: content_id,
                hsn_code: hsn_code,
                batches: []
            };

            if (typeof OfflineSync !== 'undefined') {
                OfflineSync.cacheNewProduct(onlineProd);
            }

            clearQuickAddForm();
            showToast(`Medicine "${res.name || name}" added successfully`);

            if (!isOcrMode) {
                applySelectedProductToPurchase(onlineProd);
            } else if (typeof onQuickProductSavedOCR === 'function') {
                onQuickProductSavedOCR(onlineProd);
            }
        } else {
            showToast('Error: ' + (res.error || 'Could not save medicine'), 'error');
        }
    } catch (err) {
        // Fallback to offline storage if network fails
        console.warn('Network request failed for quick-add, saving offline:', err);
        await handleSaveOffline();
    }
};

window.handleSaveProduct = function() {
    if (window._ocrQuickAddMode) {
        document.getElementById('quickName').readOnly = false;
        document.getElementById('quickName').classList.remove('bg-light');
        saveQuickProduct(true);
        return;
    }
    if (typeof pendingMissingProducts !== 'undefined' && pendingMissingProducts && pendingMissingProducts.length > 0 && typeof saveProductFromCsv === 'function') {
        saveProductFromCsv();
    } else {
        document.getElementById('quickName').readOnly = false;
        document.getElementById('quickName').classList.remove('bg-light');
        saveQuickProduct(false);
    }
};
window.handleSaveQuickProduct = window.handleSaveProduct;

/**
 * ══════════════════════════════════════════════════════════════════════
 * 11. DOM INITIALIZATION & EVENT BINDINGS
 * ══════════════════════════════════════════════════════════════════════
 */
document.addEventListener('DOMContentLoaded', function() {
    ['quickType', 'quickTax', 'quickSchedule', 'quickContent', 'quickCompany'].forEach(initQuickSelect);

    const searchInput = document.getElementById('productSearch');
    const searchResultsDiv = document.getElementById('searchResults');
    const batchInput = document.getElementById('itemBatch');
    const suggestionsDiv = document.getElementById('batchSuggestions');
    const supplierSelect = document.getElementById('supplierSelect');
    const expiryFormat = window.EP_CONFIG?.expiryFormat || 'text';

    // Supplier searchable dropdown
    (function() {
        const searchInput = document.getElementById('supplierSearchInput');
        const dropdown = document.getElementById('supplierDropdown');
        if (!searchInput || !dropdown) return;
        let supplierActiveIdx = -1;
        let filteredOptions = [];

        function getSupplierOptions() {
            return Array.from(supplierSelect.options)
                .filter(o => o.value !== '')
                .map(o => ({ value: o.value, text: o.text }));
        }

        function selectSupplier(opt) {
            if (opt.value === 'ADD_NEW') {
                dropdown.style.display = 'none';
                supplierActiveIdx = -1;
                document.getElementById('supplierName').value = searchInput.value.trim();
                ['supplierPhone', 'supplierAddress', 'supplierGst', 'supplierDl'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.value = '';
                });
                bootstrap.Modal.getOrCreateInstance(document.getElementById('supplierModal')).show();
                return;
            }
            supplierSelect.value = opt.value;
            supplierSelect.dispatchEvent(new Event('change'));
            searchInput.value = opt.text.split(' | ')[0];
            dropdown.style.display = 'none';
            supplierActiveIdx = -1;
            setTimeout(() => {
                const invEl = document.getElementById('invoiceNumber');
                if (invEl) { invEl.focus(); invEl.select(); }
            }, 50);
        }

        function updateSupplierHighlight() {
            const itemEls = dropdown.querySelectorAll('.supplier-item');
            itemEls.forEach((el, i) => {
                if (i === supplierActiveIdx) {
                    el.classList.add('supplier-item-active');
                    el.style.backgroundColor = '#ede9fe';
                    el.style.borderLeftColor = 'var(--brand)';
                    el.scrollIntoView({ block: 'nearest' });
                } else {
                    el.classList.remove('supplier-item-active');
                    el.style.backgroundColor = '';
                    el.style.borderLeftColor = 'transparent';
                }
            });
        }

        function renderDropdown(filtered) {
            filteredOptions = [...filtered];
            const q = searchInput.value.trim();
            const addNewOpt = { value: 'ADD_NEW', text: q ? `+ Add "${q}" as new supplier` : '+ Add New Supplier' };
            filteredOptions.push(addNewOpt);
            dropdown.innerHTML = '';
            
            if (filtered.length === 0 && q) {
                const noFoundDiv = document.createElement('div');
                noFoundDiv.style.cssText = 'padding:10px 14px; color:#888; font-size:0.85rem;';
                noFoundDiv.innerHTML = '<i class="fas fa-search me-1"></i> No suppliers found';
                dropdown.appendChild(noFoundDiv);
            }
            
            filtered.forEach((opt, i) => {
                const div = document.createElement('div');
                div.className = 'supplier-item';
                div.style.cssText = 'padding:9px 14px; font-size:0.88rem; cursor:pointer; border-left:3px solid transparent; transition:all 0.15s;';
                const name = opt.text.split(' | ')[0];
                const addr = opt.text.split(' | ')[1] || '';
                div.innerHTML = `<div style="font-weight:600;">${name}</div>${addr ? `<div style="font-size:0.75rem;color:#888;">${addr}</div>` : ''}`;
                div.addEventListener('mouseover', () => { supplierActiveIdx = i; updateSupplierHighlight(); });
                div.addEventListener('mousedown', (e) => { e.preventDefault(); selectSupplier(opt); });
                dropdown.appendChild(div);
            });
            
            const addNewDiv = document.createElement('div');
            addNewDiv.className = 'supplier-item';
            addNewDiv.style.cssText = 'padding:9px 14px; font-size:0.88rem; cursor:pointer; border-left:3px solid transparent; transition:all 0.15s; font-weight:bold; color:var(--brand); border-top:1px solid #e5e7eb;';
            addNewDiv.textContent = addNewOpt.text;
            const addNewIdx = filtered.length;
            addNewDiv.addEventListener('mouseover', () => { supplierActiveIdx = addNewIdx; updateSupplierHighlight(); });
            addNewDiv.addEventListener('mousedown', (e) => { e.preventDefault(); selectSupplier(addNewOpt); });
            dropdown.appendChild(addNewDiv);
            
            supplierActiveIdx = filteredOptions.length > 0 ? 0 : -1;
            updateSupplierHighlight();
            dropdown.style.display = 'block';
        }

        function syncSupplierFromInput() {
            const q = searchInput.value.toLowerCase().trim();
            if (!q) {
                if (supplierSelect.value !== '') {
                    supplierSelect.value = '';
                    supplierSelect.dispatchEvent(new Event('change'));
                }
                return;
            }
            const opts = getSupplierOptions();
            const exactOrPrefix = opts.find(o => 
                o.text.toLowerCase().split(' | ')[0].trim() === q ||
                o.text.toLowerCase().startsWith(q) ||
                q.startsWith(o.text.toLowerCase().split(' | ')[0].trim())
            );
            if (exactOrPrefix && supplierSelect.value !== exactOrPrefix.value) {
                supplierSelect.value = exactOrPrefix.value;
                supplierSelect.dispatchEvent(new Event('change'));
            }
        }

        searchInput.addEventListener('input', function() {
            const q = this.value.toLowerCase().trim();
            if (!q) { dropdown.style.display = 'none'; supplierSelect.value = ''; return; }
            syncSupplierFromInput();
            renderDropdown(getSupplierOptions().filter(o => o.text.toLowerCase().includes(q)));
        });

        searchInput.addEventListener('blur', function() {
            syncSupplierFromInput();
            debouncedCheckDuplicateInvoice(true);
        });

        searchInput.addEventListener('focus', function() {
            const q = this.value.toLowerCase().trim();
            renderDropdown(q ? getSupplierOptions().filter(o => o.text.toLowerCase().includes(q)) : getSupplierOptions());
        });

        searchInput.addEventListener('keydown', function(e) {
            const itemEls = dropdown.querySelectorAll('.supplier-item');
            if (dropdown.style.display === 'none' || itemEls.length === 0) {
                if (e.key === 'ArrowDown' || e.key === 'Enter') {
                    e.preventDefault();
                    const q = searchInput.value.toLowerCase().trim();
                    renderDropdown(q ? getSupplierOptions().filter(o => o.text.toLowerCase().includes(q)) : getSupplierOptions());
                }
                return;
            }
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                supplierActiveIdx = Math.min(supplierActiveIdx + 1, itemEls.length - 1);
                updateSupplierHighlight();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                supplierActiveIdx = Math.max(supplierActiveIdx - 1, 0);
                updateSupplierHighlight();
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                if (supplierActiveIdx >= 0 && filteredOptions[supplierActiveIdx]) {
                    e.preventDefault();
                    selectSupplier(filteredOptions[supplierActiveIdx]);
                }
            } else if (e.key === 'Escape') {
                dropdown.style.display = 'none';
                supplierActiveIdx = -1;
            }
        });

        document.addEventListener('click', function(e) {
            if (!document.getElementById('supplierSearchWrap')?.contains(e.target)) {
                dropdown.style.display = 'none';
            }
        });

        if (supplierSelect.value) {
            const sel = supplierSelect.options[supplierSelect.selectedIndex];
            if (sel) searchInput.value = sel.text.split(' | ')[0];
        }
    })();

    // Supplier credit notes
    supplierSelect.addEventListener('change', async function() {
        const sid = this.value;
        const cnSection = document.getElementById('creditNotesSection');
        const cnList = document.getElementById('creditNotesList');
        cnList.innerHTML = '';
        availableCreditNotes = [];
        calculateSummary();
        
        if (!sid) {
            cnSection.classList.add('d-none');
            return;
        }
        try {
            const resp = await fetch(`/api/supplier-unadjusted-returns/?supplier_id=${sid}`);
            const data = await resp.json();
            if (data.length > 0) {
                availableCreditNotes = data;
                data.forEach((note, idx) => {
                    cnList.innerHTML += `
                        <div class="d-flex justify-content-between align-items-center mb-1 small border-bottom pb-1">
                            <div>
                                <input type="checkbox" class="cn-checkbox form-check-input me-1" data-idx="${idx}" onchange="toggleCreditNote(${idx}, this.checked)">
                                <strong>${note.reference}</strong> (${note.return_date})
                                <div class="text-muted" style="font-size:0.65rem">Bal: ₹${note.balance.toFixed(2)}</div>
                            </div>
                            <div>
                                <input type="number" id="cn-amt-${idx}" class="form-control form-control-sm text-end cn-amt-input" style="width: 80px;" disabled value="0" max="${note.balance}" oninput="updateCreditNoteAmt(${idx}, this.value)">
                            </div>
                        </div>
                    `;
                });
                cnSection.classList.remove('d-none');
            } else {
                cnSection.classList.add('d-none');
            }
        } catch(e) {}
    });

    // Product search results rendering
    function renderPurchaseSearchResults(data) {
        searchResultsDiv.innerHTML = '';
        searchSelectedIndex = -1;
        if (data.length === 0) {
            searchResultsDiv.innerHTML = `<div class="search-item p-3 text-muted text-center"><i class="fas fa-search me-1"></i> No matching medicines found</div>`;
        } else {
            data.forEach(p => {
                const btn = document.createElement('button');
                btn.className = 'search-item d-flex justify-content-between align-items-center w-100 px-3 py-2 border-0 bg-transparent text-start';
                btn.style.outline = 'none';
                btn.innerHTML = `
                    <div style="min-width: 0; flex-grow: 1; padding-right: 14px; text-align: left;">
                        <div class="d-flex align-items-center gap-2 flex-wrap">
                            <span style="font-size: 0.92rem; font-weight: 700; color: #0f172a; line-height: 1.3;">${p.name}</span>
                            ${p.company_name ? `<span class="badge bg-light text-secondary border" style="font-size:0.7rem; font-weight:500;">${p.company_name}</span>` : ''}
                        </div>
                        ${p.salt ? `<div style="font-size: 0.76rem; color: #d97706; font-weight: 500; margin-top: 2px;"><i class="fas fa-flask me-1 text-muted"></i>${p.salt}</div>` : ''}
                        <div style="font-size: 0.74rem; color: #64748b; margin-top: 2px;">
                            <span class="me-3"><i class="fas fa-box me-1"></i>Packing: <strong>${p.packing || 'Standard'}</strong></span>
                            <span><i class="fas fa-calculator me-1"></i>Conv: <strong>×${p.conversion_factor}</strong></span>
                        </div>
                    </div>
                    <div class="text-end flex-shrink-0">
                        <span style="background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; font-size: 0.75rem; border-radius: 6px; padding: 4px 8px; font-weight: 700; white-space: nowrap;">${p.tax_rate}% GST</span>
                    </div>
                `;
                btn.onclick = () => {
                    selectedProduct = p;
                    searchInput.value = p.name;
                    renderSelectedProductBanner(p);
                    searchResultsDiv.style.display = 'none';
                    searchResultsDiv.classList.remove('open');
                    suggestionsDiv.innerHTML = '';
                    suggestionsDiv.classList.remove('show');
                    if (p.id) fetchBatchHistory(p.id);
                    loadInlinePreviousPurchases(p.id, p.name);
                    document.getElementById('itemBatch').focus();
                };
                searchResultsDiv.appendChild(btn);
            });
        }
        searchResultsDiv.classList.add('open');
        searchResultsDiv.style.display = 'block';
    }

    async function showDefaultProductsPurchase() {
        try {
            let products = [];
            if (navigator.onLine) {
                const response = await fetch('/api/products/master-search/?limit=50');
                if (response.ok) products = await response.json();
            }
            if (!products || products.length === 0) {
                if (typeof OfflineSync !== 'undefined') {
                    const store = localforage.createInstance({ name: 'ep_product_cache' });
                    products = await store.getItem('master_products') || [];
                }
            }
            if (products && products.length > 0) {
                renderPurchaseSearchResults(products);
            }
        } catch (err) {}
    }

    searchInput.addEventListener('input', async (e) => {
        const query = e.target.value.trim();
        if (query.length < 1) { showDefaultProductsPurchase(); return; }

        if (!navigator.onLine && typeof OfflineSync !== 'undefined') {
            const offlineResults = await OfflineSync.searchOfflineProducts(query, 'master');
            renderPurchaseSearchResults(offlineResults);
            return;
        }

        try {
            const resp = await fetch(`/api/products/master-search/?q=${encodeURIComponent(query)}`);
            if (resp.ok) {
                const data = await resp.json();
                renderPurchaseSearchResults(data);
            }
        } catch (err) {
            if (typeof OfflineSync !== 'undefined') {
                const offlineResults = await OfflineSync.searchOfflineProducts(query, 'master');
                renderPurchaseSearchResults(offlineResults);
            }
        }
    });

    searchInput.addEventListener('focus', () => {
        if (searchInput.value.trim().length === 0) showDefaultProductsPurchase();
    });

    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !searchResultsDiv.contains(e.target)) searchResultsDiv.style.display = 'none';
        if (!batchInput.contains(e.target) && !suggestionsDiv.contains(e.target)) suggestionsDiv.classList.remove('show');
    });

    searchInput.addEventListener('keydown', (e) => {
        const srItems = searchResultsDiv.querySelectorAll('button.search-item');
        const dropOpen = searchResultsDiv.style.display !== 'none' && srItems.length > 0;

        if (e.key === 'ArrowDown') {
            if (!dropOpen) return;
            e.preventDefault();
            searchSelectedIndex = Math.min(searchSelectedIndex + 1, srItems.length - 1);
            updateSearchSelection();
        } else if (e.key === 'ArrowUp') {
            if (!dropOpen) return;
            e.preventDefault();
            searchSelectedIndex = Math.max(searchSelectedIndex - 1, 0);
            updateSearchSelection();
        } else if (e.key === 'Enter') {
            if (dropOpen) {
                e.preventDefault();
                const targetIdx = searchSelectedIndex >= 0 ? searchSelectedIndex : 0;
                srItems[targetIdx]?.click();
                searchSelectedIndex = -1;
            }
        } else if (e.key === 'Escape') {
            searchResultsDiv.style.display = 'none';
            searchSelectedIndex = -1;
        }
    });

    batchInput.addEventListener('input', (e) => {
        const val = e.target.value.trim().toUpperCase();
        batchSelectedIndex = -1;
        if (!val) { renderBatchSuggestions(currentBatchHistory); return; }
        if (!currentBatchHistory || currentBatchHistory.length === 0) { suggestionsDiv.classList.remove('show'); return; }
        const filtered = currentBatchHistory.filter(b => (b.batch_number || '').toUpperCase().includes(val));
        renderBatchSuggestions(filtered);
    });

    batchInput.addEventListener('keydown', (e) => {
        const items = suggestionsDiv.querySelectorAll('.batch-suggestion-item');
        if (items.length === 0 || !suggestionsDiv.classList.contains('show')) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            batchSelectedIndex = Math.min(batchSelectedIndex + 1, items.length - 1);
            updateBatchSelection();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            batchSelectedIndex = Math.max(batchSelectedIndex - 1, 0);
            updateBatchSelection();
        } else if (e.key === 'Enter') {
            if (batchSelectedIndex > -1 && batchSelectedIndex < items.length) {
                e.preventDefault();
                items[batchSelectedIndex].click();
                batchSelectedIndex = -1;
            }
        } else if (e.key === 'Escape') {
            suggestionsDiv.classList.remove('show');
            batchSelectedIndex = -1;
        }
    });

    // Sync expiry hidden
    function syncExpiryHidden() {
        const hint = document.getElementById('expiryHint');
        if (expiryFormat === 'dropdown') {
            const mSelect = document.getElementById('itemExpiryMonth');
            const ySelect = document.getElementById('itemExpiryYear');
            const month = mSelect ? mSelect.value : '';
            const year = ySelect ? ySelect.value : '';
            if (month && year) {
                document.getElementById('itemExpiry').value = `${year}-${month}`;
                mSelect.classList.remove('is-invalid');
                ySelect.classList.remove('is-invalid');
                return true;
            } else {
                document.getElementById('itemExpiry').value = '';
                return false;
            }
        } else {
            const input = document.getElementById('itemExpiryInput');
            if (!input) return false;
            const val = input.value.trim();
            if (!val) {
                document.getElementById('itemExpiry').value = '';
                hint.style.display = 'none';
                input.classList.remove('is-invalid');
                return false;
            }
            const parsed = ExpiryDateHelper.parse(val);
            if (parsed) {
                document.getElementById('itemExpiry').value = parsed.iso;
                input.classList.remove('is-invalid');
                const expDate = new Date(parsed.year, parsed.month - 1, 1);
                const today = new Date(); today.setDate(1); today.setHours(0, 0, 0, 0);
                if (expDate < today) {
                    hint.style.color = '#dc3545';
                    hint.textContent = '⚠ Expiry is in the past!';
                    hint.style.display = 'block';
                } else if ((expDate - today) / (1000 * 60 * 60 * 24 * 30) < 3) {
                    hint.style.color = '#fd7e14';
                    hint.textContent = '⚠ Expires within 3 months';
                    hint.style.display = 'block';
                } else {
                    hint.style.display = 'none';
                }
                return true;
            } else {
                document.getElementById('itemExpiry').value = '';
                if (val.length >= 2) {
                    hint.style.color = '#dc3545';
                    hint.textContent = 'Format: MM-YY (e.g. 04-26 or type 0426)';
                    hint.style.display = 'block';
                    input.classList.add('is-invalid');
                }
                return false;
            }
        }
    }
    window.syncExpiryHidden = syncExpiryHidden;

    if (expiryFormat === 'dropdown') {
        document.getElementById('itemExpiryMonth')?.addEventListener('change', syncExpiryHidden);
        document.getElementById('itemExpiryYear')?.addEventListener('change', syncExpiryHidden);
    } else {
        const expInput = document.getElementById('itemExpiryInput');
        if (expInput) ExpiryDateHelper.attachAutoFormatter(expInput, syncExpiryHidden);
    }

    // Global Enter key navigation
    document.getElementById('invoiceNumber')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); document.getElementById('purchaseDate').focus(); }
    });
    document.getElementById('purchaseDate')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); document.getElementById('productSearch').focus(); }
    });

    const formInputs = (expiryFormat === 'dropdown') ? [
        'productSearch', 'itemBatch', 'itemExpiryMonth', 'itemExpiryYear',
        'itemQty', 'itemFreeQty', 'itemPrice', 'itemTax', 'itemMrp'
    ] : [
        'productSearch', 'itemBatch', 'itemExpiryInput',
        'itemQty', 'itemFreeQty', 'itemPrice', 'itemTax', 'itemMrp'
    ];

    formInputs.forEach((id, idx) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            if (id === 'productSearch') {
                if (searchResultsDiv.style.display !== 'none' && searchSelectedIndex > -1) return;
                e.preventDefault();
                if (!selectedProduct) { showToast('Select a medicine from the list', 'error'); return; }
                const batchEl = document.getElementById('itemBatch');
                batchEl.focus(); batchEl.select();
                return;
            }
            if (id === 'itemBatch') {
                if (suggestionsDiv.classList.contains('show') && batchSelectedIndex > -1) return;
                e.preventDefault();
                if (expiryFormat === 'dropdown') document.getElementById('itemExpiryMonth').focus();
                else { const expEl = document.getElementById('itemExpiryInput'); expEl.focus(); expEl.select(); }
                return;
            }
            if (id === 'itemExpiryInput') {
                e.preventDefault();
                const inputEl = document.getElementById('itemExpiryInput');
                const parsed = ExpiryDateHelper.parse(inputEl.value);
                if (!parsed) {
                    showToast('Enter a valid expiry, e.g. 04-26 or type 0426', 'error');
                    inputEl.classList.add('is-invalid');
                    inputEl.focus();
                    return;
                }
                inputEl.value = parsed.display;
                syncExpiryHidden();
                const qtyEl = document.getElementById('itemQty');
                qtyEl.focus(); qtyEl.select();
                return;
            }
            if (id === 'itemTax') {
                e.preventDefault();
                document.getElementById('itemMrp').focus();
                return;
            }
            if (id === 'itemMrp') {
                e.preventDefault();
                document.getElementById('addItemBtn').click();
                return;
            }
            e.preventDefault();
            let nextIdx = idx + 1;
            while (nextIdx < formInputs.length) {
                const nextEl = document.getElementById(formInputs[nextIdx]);
                if (nextEl && !nextEl.disabled && nextEl.readOnly !== true) {
                    nextEl.focus();
                    if (nextEl.select) nextEl.select();
                    break;
                }
                nextIdx++;
            }
        });
    });

    document.getElementById('addItemBtn')?.addEventListener('click', () => addItem());
    ['itemQty', 'itemFreeQty'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', () => updateUnitPreview());
    });
    ['itemPrice', 'itemTax', 'itemDisc'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', () => updateItemTotal());
        document.getElementById(id)?.addEventListener('change', () => updateItemTotal());
    });
    document.getElementById('summaryDiscount')?.addEventListener('input', () => calculateDiscount('amt'));
    document.getElementById('summaryDiscountPerc')?.addEventListener('input', () => calculateDiscount('perc'));
    document.getElementById('summaryRoundOff')?.addEventListener('input', () => calculateSummary());
    document.getElementById('summaryRoundOff')?.addEventListener('change', () => calculateSummary());

    if (window.EP_CONFIG?.editData) {
        populateEditData(window.EP_CONFIG.editData);
    } else {
        restorePurchaseDraft();
    }

    ['supplierSelect', 'supplierSearchInput', 'invoiceNumber', 'purchaseDate', 'summaryDiscount', 'summaryDiscountPerc', 'summaryPaymentMode'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', savePurchaseDraft);
            el.addEventListener('change', savePurchaseDraft);
        }
    });

    // Real-time live duplicate invoice check bindings
    const invInputEl = document.getElementById('invoiceNumber');
    if (invInputEl) {
        invInputEl.addEventListener('input', () => debouncedCheckDuplicateInvoice(true));
        invInputEl.addEventListener('change', () => checkDuplicateInvoice(true));
        invInputEl.addEventListener('blur', () => checkDuplicateInvoice(true));
    }
    const suppSelectEl = document.getElementById('supplierSelect');
    if (suppSelectEl) {
        suppSelectEl.addEventListener('change', () => debouncedCheckDuplicateInvoice(true));
    }

    window.addEventListener('load', () => showDefaultProductsPurchase());
});

function populateEditData(data) {
    if (!data) return;
    document.getElementById('supplierSelect').value = data.supplier_id || '';
    const _suppSel = document.getElementById('supplierSelect');
    const _suppSI = document.getElementById('supplierSearchInput');
    if (_suppSI && _suppSel.value) {
        const _selOpt = _suppSel.options[_suppSel.selectedIndex];
        if (_selOpt) _suppSI.value = _selOpt.text.split(' | ')[0];
    }
    document.getElementById('invoiceNumber').value = data.invoice_number || '';
    if (data.voucher_number) {
        const badge = document.getElementById('editVoucherBadge');
        if (badge) {
            badge.innerText = 'Voucher: ' + data.voucher_number;
            badge.classList.remove('d-none');
        }
    }
    document.getElementById('purchaseDate').value = data.purchase_date || '';
    document.getElementById('summaryDiscount').value = parseFloat(data.discount_amount || 0).toFixed(2);
    document.getElementById('summaryDiscountPerc').value = parseFloat(data.discount_percentage || 0).toFixed(2);
    if (data.payment_mode) document.getElementById('summaryPaymentMode').value = data.payment_mode;
    items = data.items || [];
    renderTable();
    calculateDiscount('amt');
}

window.addEventListener('beforeunload', function(e) {
    if (window.__isPurchaseSubmitting) return;
    savePurchaseDraft();
    if (items && items.length > 0) {
        e.preventDefault();
        e.returnValue = 'You have unsaved purchase items. Are you sure you want to leave or refresh?';
        return e.returnValue;
    }
});
