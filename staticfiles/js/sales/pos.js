    function isExpired(expiryStr) {
        if (!expiryStr || expiryStr === '—') return false;
        const today = new Date();
        const currentYear = today.getFullYear();
        const currentMonth = today.getMonth() + 1; // 1-indexed (Jan is 1)
        
        // Check format YYYY-MM-DD
        if (expiryStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
            const parts = expiryStr.split('-');
            const expYear = parseInt(parts[0]);
            const expMonth = parseInt(parts[1]);
            const expDay = parseInt(parts[2]);
            const expDate = new Date(expYear, expMonth - 1, expDay);
            const todayDateOnly = new Date(currentYear, currentMonth - 1, today.getDate());
            return expDate < todayDateOnly;
        }
        
        // Check format MM/YYYY or MM/YY or MM-YYYY
        const parts = expiryStr.split(/[-/]/);
        if (parts.length === 2) {
            let month = parseInt(parts[0]);
            let year = parseInt(parts[1]);
            if (year < 100) {
                year += 2000;
            }
            if (year < currentYear) return true;
            if (year === currentYear && month < currentMonth) return true;
        }
        return false;
    }

    const pharmacyInfo = window.POS_CONFIG?.pharmacyInfo || {};
    const tenantCity = window.POS_CONFIG?.tenantCity || "";

    const printSetup = window.POS_CONFIG?.printSetup || {};

    function getCookie(name) {
        let cookieValue = null;

        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');

            for (let cookie of cookies) {
                cookie = cookie.trim();

                if (cookie.startsWith(name + '=')) {
                    cookieValue = decodeURIComponent(
                        cookie.substring(name.length + 1)
                    );
                    break;
                }
            }
        }

        return cookieValue;
    }
    
    let cart = [];
    let mrpEditMode = false;
    let shouldFocusLastQty = false;
    let searchSelectedIndex = -1;
    const editData = window.POS_CONFIG?.editData || null;

    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
            padding: 12px 24px; border-radius: 30px; z-index: 99999; font-weight: 600;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2); color: white;
        `;
        
        if (type === 'warning' || type === 'error') {
            toast.style.background = '#f59e0b';
        } else {
            toast.style.background = '#10b981';
        }
        
        toast.innerHTML = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 500);
        }, 4000);
    }
    // ── Bill Number Badge ──
    function updateBillNumberDisplay() {
        const badge = document.getElementById('runningBillNumber');
        if (!badge) return;
        if (editData && editData.invoice_number) {
            badge.textContent = editData.invoice_number;
            badge.style.background = '#FDF1E1';
            badge.style.color = '#9A5B00';
            badge.style.border = '1.5px solid #F3D8A6';
        } else {
            const nextNum = window.POS_CONFIG?.nextInvoiceNumber || "";
            badge.textContent = nextNum ? nextNum : 'NEW';
        }
    }
    // Check if ?mode=counter is present in URL
    document.addEventListener('DOMContentLoaded', () => {
        updateBillNumberDisplay();
        
        // ── Patient details Enter key navigation ──
        const navigationOrder = [
            'billDate',
            'patientName',
            'patientAddress',
            'patientPhone',
            'doctorName',
            'summaryDiscount'
        ];

        navigationOrder.forEach((id, idx) => {
            const inputEl = document.getElementById(id);
            if (inputEl) {
                inputEl.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        if (idx < navigationOrder.length - 1) {
                            const nextEl = document.getElementById(navigationOrder[idx + 1]);
                            if (nextEl) {
                                nextEl.focus();
                                if (typeof nextEl.select === 'function') {
                                    nextEl.select();
                                }
                            }
                        } else {
                            completeOrder();
                        }
                    }
                });
            }
        });

        const discPercEl = document.getElementById('summaryDiscountPerc');
        if (discPercEl) {
            discPercEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    completeOrder();
                }
            });
        }

        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('mode') === 'counter') {
            enableCounterMode();
        } else {
            if (!editData) {
                document.getElementById('patientAddress').value = tenantCity;
            }
            // Auto focus search box on load for normal mode too
            const searchInput = document.getElementById('productSearch');
            if (searchInput) searchInput.focus();
        }
    });

    function enableCounterMode() {
        const banner = document.getElementById('counterSaleBanner');
        if (banner) {
            banner.classList.remove('d-none');
            banner.classList.add('d-flex');
        }
        
        // Fill counter sale fields
        document.getElementById('patientName').value = "COUNTER SALE";
        document.getElementById('patientAddress').value = "COUNTER";
        document.getElementById('patientPhone').value = "9999999999";
        document.getElementById('doctorName').value = "SELF";

        // Read-only fields to prevent user confusion
        document.getElementById('patientName').readOnly = true;
        document.getElementById('patientAddress').readOnly = true;
        document.getElementById('patientPhone').readOnly = true;
        document.getElementById('doctorName').readOnly = true;

        // Auto focus product search input immediately
        setTimeout(() => {
            const searchInput = document.getElementById('productSearch');
            if (searchInput) {
                searchInput.focus();
                searchInput.select();
            }
        }, 100);
    }

    function exitCounterMode() {
        // Remove query param from URL without page reload
        const url = new URL(window.location.href);
        url.searchParams.delete('mode');
        window.history.pushState({}, '', url);

        const banner = document.getElementById('counterSaleBanner');
        if (banner) {
            banner.classList.remove('d-flex');
            banner.classList.add('d-none');
        }

        // Reset fields
        document.getElementById('patientName').value = "";
        document.getElementById('patientAddress').value = tenantCity;
        document.getElementById('patientPhone').value = "";
        document.getElementById('doctorName').value = window.POS_CONFIG?.defaultDoctorName || "";

        document.getElementById('patientName').readOnly = false;
        document.getElementById('patientAddress').readOnly = false;
        document.getElementById('patientPhone').readOnly = false;
        document.getElementById('doctorName').readOnly = false;
        
        document.getElementById('productSearch').focus();
    }

    // Keyboard Shortcuts
    document.addEventListener('keydown', (e) => {
        const results = document.querySelectorAll('.batch-item');

        // Close H1/Narcotic alert modal on Enter
        const h1ModalEl = document.getElementById('h1AlertModal');
        if (e.key === 'Enter' && h1ModalEl.classList.contains('show')) {
            e.preventDefault();
            bootstrap.Modal.getInstance(h1ModalEl).hide();
            return;
        }

        // ESC close search dropdown
        if (e.key === 'Escape') {

            resultsDiv.classList.add('d-none');

            searchInput.value = '';

            searchSelectedIndex = -1;
        }

        if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
            e.preventDefault();
            document.getElementById('productSearch').focus();
        }
        
        if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
            e.preventDefault(); document.getElementById('productSearch').focus();
        }

        if (e.key === 'ArrowDown' && !resultsDiv.classList.contains('d-none')) {
            e.preventDefault();
            searchSelectedIndex = Math.min(searchSelectedIndex + 1, results.length - 1);
            updateSearchSelection();
        }

        if (e.key === 'ArrowUp' && !resultsDiv.classList.contains('d-none')) {
            e.preventDefault();
            searchSelectedIndex = Math.max(searchSelectedIndex - 1, 0);
            updateSearchSelection();
        }

        if (e.key === 'Enter' && searchSelectedIndex > -1 && !resultsDiv.classList.contains('d-none')) {
            e.preventDefault();
            results[searchSelectedIndex].querySelector('.add-btn').click();
        }

        if (e.key === 'F12') { e.preventDefault(); completeOrder(); }
        
        // Ctrl+M: Toggle MRP edit mode
        if (e.ctrlKey && e.key.toLowerCase() === 'm') {
            e.preventDefault();
            toggleMrpEditMode();
        }
    });

    function populateEditData(data) {
        if (!data) return;
        if (data.date) {
            document.getElementById('billDate').value = data.date;
        }
        document.getElementById('patientName').value = data.patient_name || '';
        document.getElementById('patientAddress').value = data.patient_address || '';
        document.getElementById('patientPhone').value = data.patient_phone || '';
        document.getElementById('doctorName').value = data.doctor_name || '';
        if (data.payment_mode) {
            const paymentOption = document.querySelector(`input[name="paymentMethod"][value="${data.payment_mode}"]`);
            if (paymentOption) paymentOption.checked = true;
        }
        document.getElementById('summaryDiscount').value = parseFloat(data.discount_amount || 0).toFixed(2);
        document.getElementById('summaryDiscountPerc').value = parseFloat(data.discount_percentage || 0).toFixed(2);
        cart = data.items.map(item => ({
            id: item.product_id,
            batch_id: item.batch_id,
            batch_no: item.batch_number,
            expiry: item.expiry_date ? item.expiry_date.substring(0, 7) : '',
            name: item.product_name,
            price: item.price,
            quantity: item.quantity,
            tax_rate: item.tax_rate,
            total: item.total,
            discount_percentage: item.discount_percentage || 0,
            max_stock: 9999
        }));
        renderCart();
        calculateDiscount('amt');
    }

    function printInvoiceOffline(data) {
        const W = printSetup.paperSize === '58mm' ? 32 : (printSetup.paperSize === '80mm' ? 42 : 55);
        const lines = [];
        lines.push(" ");
        
        const invoiceDate = new Date().toLocaleDateString('en-GB'); // dd/mm/yyyy
        
        lines.push(" " + pharmacyInfo.name.toUpperCase().substring(0, W));
        if (pharmacyInfo.address) {
            lines.push(" " + pharmacyInfo.address.toUpperCase().substring(0, W));
        }
        
        if (printSetup.showDlDetails && pharmacyInfo.dlNumber) {
            lines.push(" " + `DL: ${pharmacyInfo.dlNumber}  Ph: ${pharmacyInfo.phone || ''}`.substring(0, W));
            if (pharmacyInfo.foodLic) {
                lines.push(" " + `Food License: ${pharmacyInfo.foodLic}`.substring(0, W));
            }
        }
        
        if (printSetup.showGstDetails && pharmacyInfo.gstin) {
            lines.push(" " + `GST: ${pharmacyInfo.gstin}`.substring(0, W));
        }
        
        if (printSetup.customHeader) {
            printSetup.customHeader.split('\n').forEach(chLine => {
                lines.push(" " + chLine.substring(0, W));
            });
        }
        
        const invNoStr = `CASH MEMO: Pending Sync*  Dt: ${invoiceDate}`;
        lines.push(" " + invNoStr.padStart(W));
        lines.push(" " + "-".repeat(W));
        
        // Patient details
        const patientName = data.patient_name || 'CASH CUSTOMER';
        lines.push(" " + `Pt  : ${patientName}`.substring(0, W));
        if (data.patient_address) {
            lines.push(" " + `Addr: ${data.patient_address}`.substring(0, W));
        }
        const doctorName = data.doctor_name || 'SELF';
        lines.push(" " + `Dr  : ${doctorName}`.substring(0, W));
        lines.push(" " + "-".repeat(W));
        
        // Items header
        if (W >= 65) {
            lines.push(" " + "PRODUCT".padEnd(28) + "MFG".padEnd(6) + "BATCH".padEnd(9) + "EXP".padEnd(6) + "QT".padStart(4) + "VALUE".padStart(10));
        } else {
            lines.push(" " + "PRODUCT".padEnd(22) + "MFG".padEnd(5) + "BATCH".padEnd(8) + "EXP".padEnd(6) + "QT".padStart(4) + "VALUE".padStart(10));
        }
        lines.push(" " + "-".repeat(W));
        
        // Items
        let totalQty = 0;
        cart.forEach(item => {
            totalQty += item.quantity;
            let productName = item.name.toUpperCase();
            if (W >= 65) {
                productName = productName.substring(0, 27);
            } else {
                productName = productName.substring(0, 21);
            }
            
            const batchNo = item.batch_no || 'OFFLINE';
            const exp = item.expiry || '—';
            const mfg = '—';
            const qty = item.quantity.toString();
            const value = (item.price * item.quantity).toFixed(2);
            
            if (W >= 65) {
                lines.push(" " + productName.padEnd(28) + mfg.padEnd(6) + batchNo.padEnd(9) + exp.padEnd(6) + qty.padStart(4) + value.padStart(10));
            } else {
                lines.push(" " + productName.padEnd(22) + mfg.padEnd(5) + batchNo.padEnd(8) + exp.padEnd(6) + qty.padStart(4) + value.padStart(10));
            }
        });
        
        lines.push(" " + "-".repeat(W));
        
        // Totals
        const subTotalStr = `Sub Total:  ₹${data.sub_total.toFixed(2)}`;
        lines.push(" " + subTotalStr.padStart(W));
        if (data.tax_amount > 0) {
            const taxStr = `Tax Amount: ₹${data.tax_amount.toFixed(2)}`;
            lines.push(" " + taxStr.padStart(W));
        }
        if (data.discount_amount > 0) {
            const discStr = `Discount:   X${data.discount_amount.toFixed(2)}`;
            const discStrFixed = discStr.replace('X', '₹');
            lines.push(" " + discStrFixed.padStart(W));
        }
        if (data.round_off !== 0) {
            const roStr = `Round Off:  X${data.round_off.toFixed(2)}`;
            const roStrFixed = roStr.replace('X', '₹');
            lines.push(" " + roStrFixed.padStart(W));
        }
        lines.push(" " + "-".repeat(W));
        
        const grandTotalStr = `GRAND TOTAL: X${data.total_amount.toFixed(2)}`;
        const grandTotalStrFixed = grandTotalStr.replace('X', '₹');
        lines.push(" " + grandTotalStrFixed.padStart(W));
        
        const totalItemsStr = `Total Qty: ${totalQty} (${cart.length} items)`;
        lines.push(" " + totalItemsStr.substring(0, W));
        lines.push(" " + "-".repeat(W));
        
        if (printSetup.customFooter) {
            printSetup.customFooter.split('\n').forEach(fLine => {
                lines.push(" " + fLine.substring(0, W));
            });
        }
        
        if (printSetup.showPharmacistSignature) {
            lines.push("\n\n" + "For Pharmacist".padStart(W));
        }
        
        const billText = lines.join('\n');
        
        const printWindow = window.open('', '_blank', 'width=600,height=600');
        printWindow.document.write(`
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Print Offline Bill</title>
                <style>
                    body { margin: 0; padding: 0; }
                    pre {
                        font-family: "Courier New", monospace;
                        font-size: 12px;
                        font-weight: bold;
                        line-height: 1.15;
                        margin: 0;
                        padding: 0 0 0 3mm;
                        white-space: pre;
                    }
                    @media print {
                        @page {
                            size: ${printSetup.paperSize === 'A4' ? 'A4' : '80mm auto'};
                            margin: 0;
                        }
                    }
                </style>
            </head>
            <body>
                <pre>${billText}</pre>
                <script>
                    window.onload = function() {
                        window.print();
                        setTimeout(() => window.close(), 500);
                    };
                <\/script>
            </body>
            </html>
        `);
        printWindow.document.close();
    }

    function updateSearchSelection() {
        const results = document.querySelectorAll('.batch-item');
        results.forEach((el, idx) => {
            if (idx === searchSelectedIndex) {
                el.classList.add('selected-batch');
                el.scrollIntoView({ block: 'nearest' });
            } else {
                el.classList.remove('selected-batch');
            }
        });
    }

    // Product Search — In-Memory Cache with Real-time Stock Mutation
    const searchInput = document.getElementById('productSearch');
    const resultsDiv = document.getElementById('searchResults');

    let _posSearchCache = {};       // query → API data
    let _posDebounceTimer = null;   // debounce handle

    function deductSoldItemsFromPosCache(soldItems) {
        if (!soldItems || !Array.isArray(soldItems) || soldItems.length === 0) return;

        // 1. Mutate in-memory search cache without hitting DB (0ms response)
        Object.keys(_posSearchCache).forEach(query => {
            const productList = _posSearchCache[query]?.results || _posSearchCache[query]?.products || _posSearchCache[query] || [];
            if (Array.isArray(productList)) {
                productList.forEach(prod => {
                    if (Array.isArray(prod.batches)) {
                        prod.batches.forEach(b => {
                            soldItems.forEach(sold => {
                                if (Number(b.batch_id) === Number(sold.batch_id)) {
                                    b.stock = Math.max(0, (Number(b.stock) || 0) - (Number(sold.quantity) || 0));
                                }
                            });
                        });
                        const totalRemaining = prod.batches.reduce((sum, b) => sum + (Number(b.stock) || 0), 0);
                        if (totalRemaining <= 0) {
                            prod.out_of_stock = true;
                        }
                    }
                });
            }
        });

        // 2. Mutate LocalForage offline product cache
        if (typeof localforage !== 'undefined') {
            try {
                const store = localforage.createInstance({ name: 'ep_product_cache' });
                store.getItem('pos_products').then(cachedProducts => {
                    if (Array.isArray(cachedProducts)) {
                        cachedProducts.forEach(prod => {
                            if (Array.isArray(prod.batches)) {
                                prod.batches.forEach(b => {
                                    soldItems.forEach(sold => {
                                        if (Number(b.batch_id) === Number(sold.batch_id)) {
                                            b.stock = Math.max(0, (Number(b.stock) || 0) - (Number(sold.quantity) || 0));
                                        }
                                    });
                                });
                            }
                        });
                        store.setItem('pos_products', cachedProducts);
                    }
                }).catch(() => {});
            } catch (e) {}
        }
    }
    window.deductSoldItemsFromPosCache = deductSoldItemsFromPosCache;

    function clearPosSearchCache() {
        _posSearchCache = {};
    }
    window.clearPosSearchCache = clearPosSearchCache;

    async function showDefaultProducts() {
        try {
            let products = [];
            if (navigator.onLine) {
                const response = await fetch('/api/products/search/?limit=50');
                if (response.ok) {
                    products = await response.json();
                }
            }
            if (!products || products.length === 0) {
                if (typeof OfflineSync !== 'undefined') {
                    const store = localforage.createInstance({ name: 'ep_product_cache' });
                    products = await store.getItem('pos_products') || [];
                }
            }
            
            if (products && products.length > 0) {
                renderSearchResults({ results: products });
            } else {
                resultsDiv.innerHTML = '<div class="p-3 text-center text-muted small">No items cached yet. Search while online to cache items.</div>';
                resultsDiv.classList.remove('d-none');
            }
        } catch (err) {
            console.error('Failed to load default products', err);
        }
    }

    function renderSearchResults(data) {
        resultsDiv.innerHTML = '';
        searchSelectedIndex = -1;
        let batchIndex = 0;

        // Safe data extraction
        const products = data?.results || data?.products || data || [];

        if (products.length === 0) {
            resultsDiv.innerHTML = `
                <div class="p-3 text-center text-muted small">
                    No items found. 
                    <button class="btn btn-link btn-sm" data-bs-toggle="modal" data-bs-target="#quickAddModal">
                        Add New?
                    </button>
                </div>`;
            resultsDiv.classList.remove('d-none');
            return;
        }
        products.forEach(product => {
            const productGroup = document.createElement('div');
            productGroup.className = 'list-group-item p-3 border-bottom bg-white';

            // ── Product header info ──
            const contentBadge = product.content
                ? `<span class="badge bg-light text-secondary border x-small me-1"><i class="fas fa-flask me-1"></i>${product.content}</span>`
                : '';
            const companyBadge = product.company
                ? `<span class="badge bg-light text-muted border x-small">${product.company}</span>`
                : '';

            if (product.out_of_stock) {
                // Out of stock — show greyed card with substitute button
                productGroup.innerHTML = `
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="flex-grow-1">
                            <div class="fw-bold text-muted h6 mb-0" style="text-decoration:line-through;opacity:.6;">${product.name}</div>
                            <div class="mt-1">${contentBadge}${companyBadge}</div>
                            <div class="text-muted x-small mt-1">Packing: ${product.packing || '—'}</div>
                        </div>
                        <div class="d-flex flex-column align-items-end gap-1">
                            <span class="badge bg-danger-subtle text-danger border border-danger-subtle"><i class="fas fa-times-circle me-1"></i>Out of Stock</span>
                            ${product.content ? `
                            <button class="btn btn-warning btn-sm px-3 rounded-pill fw-bold sub-btn mt-1"
                                onclick="openSubstitutes(${product.id}, '${product.name.replace(/'/g,"\\'")}')"
                                title="Find same-composition drugs in stock">
                                <i class="fas fa-exchange-alt me-1"></i>Substitute
                            </button>` : '<small class="text-muted" style="font-size:9px;">No content linked</small>'}
                        </div>
                    </div>`;
                resultsDiv.appendChild(productGroup);
                return; // no batches to render
            }

            let batchesHtml = '';
            product.batches.forEach(b => {
                const expired = isExpired(b.expiry);
                const borderClass = expired ? 'border-danger' : 'border-primary';
                const bgClass = expired ? 'bg-danger-soft' : 'bg-light';
                const btnHtml = expired
                    ? `<button type="button" class="btn btn-danger btn-sm ms-3 px-3 rounded-pill fw-bold" onclick="alert('Item &quot;${product.name.replace(/"/g, '&quot;').replace(/'/g, "\\'")}&quot; is EXPIRED (Exp: ${b.expiry}) and CANNOT be sold!')"><i class="fas fa-ban me-1"></i>Expired</button>`
                    : `<button type="button" class="btn btn-primary btn-sm ms-3 px-3 rounded-pill fw-bold add-btn" 
                        onclick='addToCart({
                            id: ${product.id}, 
                            batch_id: ${b.batch_id}, 
                            name: "${product.name.replace(/"/g,"&quot;")}", 
                            batch_no: "${b.batch_no}", 
                            expiry: "${b.expiry}", 
                            price: ${b.price}, 
                            tax_rate: ${product.tax_rate}, 
                            stock: ${b.stock},
                            schedule: "${(product.schedule || '').replace(/"/g,'&quot;')}"
                        })'>+ ADD</button>`;

                batchesHtml += `
                <div class="d-flex justify-content-between align-items-center mt-2 p-3 rounded ${bgClass} border-start border-4 ${borderClass} batch-item" data-batch-index="${batchIndex++}" ${expired ? 'style="background-color: rgba(220, 53, 69, 0.08) !important; border-color: #dc3545 !important;"' : ''}>
                    <div class="d-flex align-items-center flex-grow-1" style="min-width: 0;">
                        <!-- Price & Batch -->
                        <div class="d-flex flex-column justify-content-center" style="min-width: 140px;">
                            <div class="fw-extrabold text-primary fs-5" style="font-family: 'JetBrains Mono', monospace; font-weight: 800;">₹${b.price.toFixed(2)}</div>
                            <div class="mt-1">
                                <span class="badge ${expired ? 'bg-danger text-white' : 'bg-white text-dark'} border px-2 py-1" style="font-size: 0.78rem; font-family: 'JetBrains Mono', monospace;">B: ${b.batch_no}</span>
                            </div>
                        </div>
                        
                        <!-- Expiry Date (Centered & Large) -->
                        <div class="flex-grow-1 px-3 d-flex align-items-center">
                            <span class="${expired ? 'text-danger fw-bold' : 'text-dark fw-semibold'}" style="font-size: 0.9rem;">
                                <i class="far fa-clock me-1 text-muted"></i>Exp: <strong style="font-size: 0.95rem; font-family: 'JetBrains Mono', monospace;">${b.expiry}</strong>
                                ${expired ? ' <span class="badge bg-danger text-white ms-1">EXPIRED</span>' : ''}
                            </span>
                        </div>
                        
                        <!-- Stock Qty Badge -->
                        <div class="px-2">
                            <span class="badge ${expired ? 'bg-danger' : (b.stock <= 0 ? 'bg-secondary' : (b.stock <= 5 ? 'bg-warning text-dark' : 'bg-success'))} text-white px-3 py-2 fw-bold" style="font-size: 0.88rem; font-family: 'JetBrains Mono', monospace;">
                                ${expired ? 'Expired' : b.stock + ' left'}
                            </span>
                        </div>
                    </div>
                    <div class="ps-2">
                        ${btnHtml}
                    </div>
                </div>`;
            });

            productGroup.innerHTML = `
                <div class="d-flex justify-content-between align-items-start mb-1">
                    <div>
                        <div class="fw-bold text-dark h6 mb-0">${product.name}</div>
                        <div class="mt-1">${contentBadge}${companyBadge}</div>
                        <div class="text-muted x-small mt-1">Packing: ${product.packing || '1'} | Factor: ${product.conversion_factor}</div>
                    </div>
                    <div class="d-flex flex-column align-items-end gap-1">
                        <span class="badge bg-info-soft text-info x-small">${product.batches.length} Batch(es)</span>
                        <div class="d-flex gap-1 mt-1">
                            ${product.content ? `<button class="btn btn-outline-secondary btn-sm rounded-pill x-small px-2" onclick="openSubstitutes(${product.id}, '${product.name.replace(/'/g,"\\'").replace(/"/g,"&quot;")}')"><i class="fas fa-exchange-alt me-1"></i>Alt</button>` : ''}
                            <button class="btn btn-outline-primary btn-sm rounded-pill x-small px-2" onclick="openProductHistoryInline(${product.id}, '${product.name.replace(/'/g,"\\'").replace(/"/g,"&quot;")}')"><i class="fas fa-history me-1"></i>History</button>
                        </div>
                    </div>
                </div>
                <div class="batch-list">${batchesHtml}</div>
            `;
        });
        resultsDiv.classList.remove('d-none');
    }

    searchInput.addEventListener('input', (e) => {
        clearTimeout(_posDebounceTimer);
        const query = e.target.value.trim();
        if (query.length < 1) { 
            showDefaultProducts();
            return; 
        }

        // Cache hit
        if (_posSearchCache[query]) {
            renderSearchResults(_posSearchCache[query]);
            return;
        }

    _posDebounceTimer = setTimeout(async () => {
        try {
            // ── Immediately use offline cache if no connection ──
            if (!navigator.onLine) {
                const offlineResults = await OfflineSync.searchOfflineProducts(query, 'pos');
                renderSearchResults(offlineResults);
                return;
            }

            const response = await fetch(`/api/products/search/?q=${encodeURIComponent(query)}`);
            if (!response.ok) {
                throw new Error('Offline');
            }
            const data = await response.json();
            
            // Populate memory cache for 0ms subsequent search hits
            _posSearchCache[query] = data;

            renderSearchResults(data);
        } catch (err) {
            // Network failed — use cached data
            const offlineResults = await OfflineSync.searchOfflineProducts(query, 'pos');
            renderSearchResults(offlineResults);
        }
    }, 300);
    
    });

    searchInput.addEventListener('focus', () => {
        if (searchInput.value.trim().length === 0) {
            showDefaultProducts();
        }
    });

    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !resultsDiv.contains(e.target)) {
            resultsDiv.classList.add('d-none');
        }
    });

    // Load default products on load
    window.addEventListener('load', () => {
        showDefaultProducts();
    });

    // ── Substitute lookup ──────────────────────────────────────────
    async function openSubstitutes(productId, productName) {
        // Close search dropdown
        resultsDiv.classList.add('d-none');

        document.getElementById('subModalSubtitle').textContent = `Substitutes for: ${productName}`;
        document.getElementById('substituteLoader').classList.remove('d-none');
        document.getElementById('substituteList').classList.add('d-none');
        document.getElementById('substituteEmpty').classList.add('d-none');

        const modal = new bootstrap.Modal(document.getElementById('substituteModal'));
        modal.show();

        const resp = await fetch(`/api/products/substitute/?product_id=${productId}`);
        const subs = await resp.json();

        document.getElementById('substituteLoader').classList.add('d-none');

        if (subs.length === 0) {
            document.getElementById('substituteEmpty').classList.remove('d-none');
            return;
        }

        const listEl = document.getElementById('substituteList');
        listEl.innerHTML = '';

        // content badge (same for all)
        const contentLabel = subs[0]?.content || '';
        if (contentLabel) {
            listEl.innerHTML += `<div class="mb-3 p-2 rounded" style="background:#fff8e1;border-left:3px solid #f59e0b;">
                <span class="small fw-bold text-warning"><i class="fas fa-flask me-1"></i>Composition: </span>
                <span class="small">${contentLabel}</span>
            </div>`;
        }

        subs.forEach(s => {
            const batches = s.batches.map(b => {
                const expired = isExpired(b.expiry);
                const borderClass = expired ? 'border-danger' : 'border-success';
                const bgClass = expired ? 'bg-danger-soft' : 'bg-light';
                const btnHtml = expired
                    ? `<button type="button" class="btn btn-danger btn-sm px-3 rounded-pill fw-bold" onclick="alert('Item &quot;${s.name.replace(/"/g, '&quot;').replace(/'/g, "\\'")}&quot; is EXPIRED (Exp: ${b.expiry}) and CANNOT be sold!')"><i class="fas fa-ban me-1"></i>Expired</button>`
                    : `<button type="button" class="btn btn-success btn-sm px-3 rounded-pill fw-bold"
                            onclick='addToCart({id:${s.id},batch_id:${b.batch_id},name:"${s.name.replace(/"/g,"&quot;")}",batch_no:"${b.batch_no}",expiry:"${b.expiry}",price:${b.price},tax_rate:${s.tax_rate},stock:${b.stock},schedule:"${(s.schedule || '').replace(/"/g,'&quot;')}"}); bootstrap.Modal.getInstance(document.getElementById("substituteModal")).hide();'>
                            + ADD
                        </button>`;
                
                return `
                <div class="d-flex justify-content-between align-items-center mt-2 p-3 rounded ${bgClass} border-start border-3 ${borderClass}" ${expired ? 'style="background-color: rgba(220, 53, 69, 0.08) !important; border-color: #dc3545 !important;"' : ''}>
                    <div class="d-flex align-items-center flex-grow-1" style="min-width: 0;">
                        <!-- Price & Batch -->
                        <div class="d-flex flex-column justify-content-center" style="min-width: 130px;">
                            <div class="fw-extrabold text-success fs-5" style="font-family: 'JetBrains Mono', monospace; font-weight: 800;">₹${b.price.toFixed(2)}</div>
                            <div class="mt-1">
                                <span class="badge ${expired ? 'bg-danger text-white' : 'bg-white text-dark'} border px-2 py-1" style="font-size: 0.78rem; font-family: 'JetBrains Mono', monospace;">B: ${b.batch_no}</span>
                            </div>
                        </div>
                        
                        <!-- Expiry (Center) -->
                        <div class="flex-grow-1 px-2 d-flex align-items-center">
                            <span class="${expired ? 'text-danger fw-bold' : 'text-dark fw-semibold'}" style="font-size: 0.9rem;">
                                <i class="far fa-clock me-1 text-muted"></i>Exp: <strong style="font-size: 0.95rem; font-family: 'JetBrains Mono', monospace;">${b.expiry}</strong>
                                ${expired ? ' <span class="badge bg-danger text-white ms-1">EXPIRED</span>' : ''}
                            </span>
                        </div>
                        
                        <!-- Stock Qty -->
                        <div class="px-2">
                            <span class="badge ${expired ? 'bg-danger' : (b.stock <= 5 ? 'bg-warning text-dark' : 'bg-success')} text-white px-3 py-2 fw-bold" style="font-size: 0.88rem; font-family: 'JetBrains Mono', monospace;">
                                ${expired ? 'Expired' : b.stock + ' left'}
                            </span>
                        </div>
                    </div>
                    <div class="ps-2">
                        ${btnHtml}
                    </div>
                </div>`;
            }).join('');

            listEl.innerHTML += `
                <div class="card border-0 shadow-sm rounded-3 mb-3">
                    <div class="card-body p-3">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <div>
                                <div class="fw-bold">${s.name}</div>
                                <div class="text-muted x-small">${s.company} &nbsp;·&nbsp; ${s.packing || '—'}</div>
                            </div>
                            <span class="badge bg-success-subtle text-success border border-success-subtle">In Stock</span>
                        </div>
                        ${batches}
                    </div>
                </div>`;
        });
        listEl.classList.remove('d-none');
    }

    async function openProductHistoryInline(productId, productName) {
        // Close search dropdown to keep it clean
        resultsDiv.classList.add('d-none');

        document.getElementById('historyModalProductName').textContent = productName;
        
        // Show loaders
        const salesTbody = document.querySelector('#inlineSalesTable tbody');
        const purchasesTbody = document.querySelector('#inlinePurchasesTable tbody');
        
        salesTbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Loading sales & customer records...</td></tr>';
        purchasesTbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Loading past purchase invoices...</td></tr>';

        const modal = new bootstrap.Modal(document.getElementById('inlineHistoryModal'));
        modal.show();

        try {
            const resp = await fetch(`/product-history/?product_id=${productId}&ajax=1`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await resp.json();

            // Render Sales
            salesTbody.innerHTML = '';
            let totalSalesQty = 0;
            if (!data.sales || data.sales.length === 0) {
                salesTbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">No sales entries recorded for this medicine.</td></tr>';
                document.getElementById('inlineSalesFoot').style.display = 'none';
            } else {
                data.sales.forEach(s => {
                    totalSalesQty += (Number(s.quantity) || 0);
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td>${s.date}</td>
                        <td><span class="badge bg-light text-dark border">${s.invoice_number}</span></td>
                        <td class="fw-bold text-dark">${s.patient_name}</td>
                        <td><span class="badge bg-warning-soft text-warning px-2 py-1">${s.batch_number}</span></td>
                        <td class="fw-bold">${s.quantity}</td>
                        <td>₹${s.unit_price.toFixed(2)}</td>
                        <td class="text-end fw-bold text-success">₹${s.total.toFixed(2)}</td>
                    `;
                    salesTbody.appendChild(row);
                });
                document.getElementById('inlineTotalSalesQty').textContent = totalSalesQty;
                document.getElementById('inlineSalesFoot').style.display = 'table-footer-group';
            }

            // Render Purchases
            purchasesTbody.innerHTML = '';
            let totalPurchasesQty = 0;
            let totalFreeQty = 0;
            if (!data.purchases || data.purchases.length === 0) {
                purchasesTbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-muted">No purchase entries recorded for this medicine.</td></tr>';
                document.getElementById('inlinePurchasesFoot').style.display = 'none';
            } else {
                data.purchases.forEach(p => {
                    const qty = Number(p.quantity) || 0;
                    const freeQty = Number(p.free_quantity) || 0;
                    totalPurchasesQty += (qty + freeQty);
                    totalFreeQty += freeQty;
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td>${p.date}</td>
                        <td><span class="badge bg-light text-dark border">${p.invoice_number}</span></td>
                        <td class="fw-bold text-dark">${p.supplier_name}</td>
                        <td><span class="badge bg-secondary-soft text-secondary px-2 py-1">${p.batch_number}</span></td>
                        <td class="fw-bold">${qty}</td>
                        <td class="fw-bold ${freeQty > 0 ? 'text-success' : 'text-muted'}">${freeQty}</td>
                        <td>₹${p.purchase_price.toFixed(2)}</td>
                        <td class="text-end fw-bold text-primary">₹${p.total.toFixed(2)}</td>
                    `;
                    purchasesTbody.appendChild(row);
                });
                const totalEl = document.getElementById('inlineTotalPurchasesQty');
                if (totalFreeQty > 0) {
                    totalEl.innerHTML = `${totalPurchasesQty} <span class="fs-6 text-muted fw-normal">(${totalPurchasesQty - totalFreeQty} + ${totalFreeQty} free)</span>`;
                } else {
                    totalEl.textContent = totalPurchasesQty;
                }
                document.getElementById('inlinePurchasesFoot').style.display = 'table-footer-group';
            }
        } catch (error) {
            console.error('Error fetching product history inline:', error);
            salesTbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-danger">Error loading sales history</td></tr>';
            purchasesTbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-danger">Error loading purchase history</td></tr>';
        }
    }

    function showH1Alert(productName, scheduleLabel) {
        document.getElementById('h1AlertProductName').textContent = productName;
        document.getElementById('h1AlertScheduleLabel').textContent = scheduleLabel || 'SCHEDULE H1';
        const h1ModalEl = document.getElementById('h1AlertModal');
        const modal = new bootstrap.Modal(h1ModalEl);
        // After user clicks "Understood", focus the last qty input
        h1ModalEl.addEventListener('hidden.bs.modal', () => {
            const inputs = document.querySelectorAll('#posTable tbody .qty-input');
            const lastQtyInput = inputs[inputs.length - 1];
            if (lastQtyInput) {
                lastQtyInput.focus();
                lastQtyInput.select();
            }
        }, { once: true });
        modal.show();
    }

    function addToCart(product) {
        if (isExpired(product.expiry)) {
            alert(`Item "${product.name}" is EXPIRED (Exp: ${product.expiry}) and CANNOT be sold!`);
            return;
        }

        if (product.stock <= 0) {
            return alert('Out of stock!');
        }

        // ── Schedule H1 / Narcotic Drug Alert ──
        const scheduleStr = (product.schedule || '').toUpperCase();
        if (scheduleStr.includes('H1') || scheduleStr.includes('NARCOTIC')) {
            showH1Alert(product.name, product.schedule);
        }

        const existing = cart.find(
            item =>
                item.id === product.id &&
                item.batch_id === product.batch_id
        );

        if (existing) {

            existing.quantity++;

        } else {

            cart.push({
                id: product.id,
                batch_id: product.batch_id,
                name: product.name,
                batch_no: product.batch_no,
                expiry: product.expiry,
                price: product.price,
                tax_rate: product.tax_rate,
                quantity: 1,
                max_stock: product.stock
            });
        }

        searchInput.value = '';

        resultsDiv.classList.add('d-none');

        shouldFocusLastQty = true;

        renderCart();
    }

    function renderCart() {
        const tbody = document.querySelector('#posTable tbody');
        const emptyState = document.getElementById('emptyState');

        tbody.innerHTML = '';

        if (cart.length === 0) {

            emptyState.classList.remove('d-none');

        } else {

            emptyState.classList.add('d-none');

            cart.forEach((item, index) => {

                const total = item.price * item.quantity;

                const basePrice = item.price / (1 + item.tax_rate / 100);

                const taxAmount = item.price - basePrice;

                const totalTaxAmount = taxAmount * item.quantity;

                const tr = document.createElement('tr');

                tr.className = 'cart-row';

                tr.innerHTML = `
                    <td class="ps-4">
                        <div class="fw-bold text-dark small">${item.name}</div>
                        <div class="text-muted x-small">Exp: ${item.expiry}</div>
                    </td>

                    <td>
                        <div class="badge bg-light text-muted x-small">
                            B: ${item.batch_no}
                        </div>
                    </td>

                    <td class="small">
                        <div class="d-flex align-items-center" style="width: 95px;">
                            <span class="small me-1">₹</span>
                            <input type="number" step="0.01"
                                class="form-control form-control-sm mrp-input fw-bold"
                                value="${item.price.toFixed(2)}"
                                data-index="${index}"
                                min="0"
                                oninput="updateMrp(${index}, this.value)"
                                onkeydown="handleMrpKeydown(event, ${index})"
                                style="width: 80px; text-align: left; padding: 2px 4px; border: ${mrpEditMode ? '1px solid var(--brand) !important' : 'none !important'}; background: ${mrpEditMode ? '#fff !important' : 'transparent !important'}; cursor: ${mrpEditMode ? 'text' : 'default'};"
                                ${mrpEditMode ? '' : 'readonly'}>
                        </div>
                    </td>

                    <td>
                        <input type="number"
                            class="form-control form-control-sm border-0 bg-light text-center fw-bold qty-input"
                            value="${item.quantity}"
                            data-index="${index}"
                            min="1"
                            max="${item.max_stock}"
                            oninput="updateQty(${index}, this.value)"
                            onkeydown="handleQtyKeydown(event, ${index})"
                            style="width:70px; cursor:text; border:1px solid #dee2e6 !important;">
                    </td>

                    <td class="text-primary small">
                        ₹${totalTaxAmount.toFixed(2)}
                        <span class="text-muted x-small">
                            (${item.tax_rate}% incl.)
                        </span>
                    </td>

                    <td class="fw-bold small">
                        ₹${total.toFixed(2)}
                    </td>

                    <td class="text-end pe-4">
                        <button class="btn btn-sm text-danger border-0"
                            onclick="removeFromCart(${index})">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </td>
                `;

                tbody.appendChild(tr);
            });

            if (shouldFocusLastQty) {
                setTimeout(() => {
                    const inputs = tbody.querySelectorAll(mrpEditMode ? '.mrp-input' : '.qty-input');
                    const lastInput = inputs[inputs.length - 1];
                    if (lastInput) {
                        lastInput.focus();
                        if (typeof lastInput.select === 'function') {
                            lastInput.select();
                        }
                    }
                    shouldFocusLastQty = false;
                }, 50);
            }
        }

        calculateGrandTotal();
        if (typeof savePosDraft === 'function') {
            savePosDraft();
        }
    }

    function handleQtyKeydown(event, index) {
        if (event.key === 'Enter') {
            event.preventDefault();
            // Clear search and focus on it for next item
            document.getElementById('productSearch').value = '';
            document.getElementById('productSearch').focus();
            document.getElementById('searchResults').classList.add('d-none');
        } else if (event.key === 'Escape') {
            event.preventDefault();
            document.getElementById('productSearch').focus();
        } else if (event.key === 'Tab') {
            // If this is the LAST qty row, Tab should jump to Patient Details
            const allQtyInputs = document.querySelectorAll('.qty-input');
            const isLast = index === cart.length - 1;
            if (isLast && !event.shiftKey) {
                event.preventDefault();
                focusPatientDetails();
            }
            // If not last, let Tab naturally move to next qty input (browser default)
        }
    }

    function updateMrp(index, val) {
        const item = cart[index];
        const newPrice = parseFloat(val) || 0;
        item.price = newPrice;
        
        // Update only the total and tax cells of this row (avoids losing focus)
        const rows = document.querySelectorAll('#posTable tbody tr');
        if (rows[index]) {
            const total = item.price * item.quantity;
            const basePrice = item.price / (1 + item.tax_rate / 100);
            const taxAmount = (item.price - basePrice) * item.quantity;
            
            // Total column is 6th td (index 5)
            const totalCell = rows[index].querySelectorAll('td')[5];
            if (totalCell) totalCell.innerHTML = `₹${total.toFixed(2)}`;
            
            // GST/Tax column is 5th td (index 4)
            const taxCell = rows[index].querySelectorAll('td')[4];
            if (taxCell) taxCell.innerHTML = `₹${taxAmount.toFixed(2)} <span class="text-muted x-small">(${item.tax_rate}% incl.)</span>`;
        }
        calculateGrandTotal();
    }

    function handleMrpKeydown(event, index) {
        if (event.key === 'Enter') {
            event.preventDefault();
            // Move focus to the quantity input of the same row
            const rows = document.querySelectorAll('#posTable tbody tr');
            if (rows[index]) {
                const qtyInput = rows[index].querySelector('.qty-input');
                if (qtyInput) {
                    qtyInput.focus();
                    qtyInput.select();
                }
            }
        } else if (event.key === 'Escape') {
            event.preventDefault();
            document.getElementById('productSearch').focus();
        } else if (event.key === 'Tab') {
            const isLast = index === cart.length - 1;
            if (isLast && !event.shiftKey) {
                event.preventDefault();
                focusPatientDetails();
            }
        }
    }

    function toggleMrpEditMode() {
        mrpEditMode = !mrpEditMode;
        
        // Re-render the cart so inputs make editability state visible
        renderCart();
        
        // If edit mode is enabled, focus the MRP input of the last item in the cart
        if (mrpEditMode && cart.length > 0) {
            setTimeout(() => {
                const mrpInputs = document.querySelectorAll('.mrp-input');
                const lastMrpInput = mrpInputs[mrpInputs.length - 1];
                if (lastMrpInput) {
                    lastMrpInput.focus();
                    lastMrpInput.select();
                }
            }, 50);
            showToast("POS modify mode: MRP inputs are now editable!", "success");
        } else {
            showToast("POS modify mode disabled.", "info");
        }
    }

    function focusPatientDetails() {
        const patientNameInput = document.getElementById('patientName');
        if (!patientNameInput) return;

        // Scroll sidebar into view smoothly
        patientNameInput.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Pulse-highlight the entire Patient Details section
        const section = patientNameInput.closest('.mb-4');
        if (section) {
            section.classList.add('patient-section-pulse');
            setTimeout(() => section.classList.remove('patient-section-pulse'), 1200);
        }

        // Focus the name field after scroll settles
        setTimeout(() => {
            patientNameInput.focus();
            patientNameInput.select();
        }, 180);
    }

    async function saveQuickProduct() {
        const name = (document.getElementById('quickName')?.value || '').trim();
        const packing = (document.getElementById('quickPacking')?.value || '').trim();
        const conv = parseInt(document.getElementById('quickConv')?.value) || 1;
        const tax_id = document.getElementById('quickTax')?.value || null;

        if (!name) return showToast('Medicine name is required', 'error');

        // Extract Tax Rate
        const taxSelect = document.getElementById('quickTax');
        let taxRate = 0;
        if (taxSelect && taxSelect.selectedIndex >= 0) {
            const opt = taxSelect.options[taxSelect.selectedIndex];
            const m = (opt.text || '').match(/(\d+(\.\d+)?)/);
            if (m) taxRate = parseFloat(m[1]) || 0;
        }

        const data = {
            name: name,
            packing: packing,
            conversion_factor: conv,
            tax_id: tax_id
        };

        const handleOfflineSave = async () => {
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

            // Clear in-memory search cache so newly added product is found immediately
            clearPosSearchCache();

            const modalEl = document.getElementById('quickAddModal');
            if (modalEl) {
                const modal = bootstrap.Modal.getInstance(modalEl) || bootstrap.Modal.getOrCreateInstance(modalEl);
                modal.hide();
            }

            // Reset inputs
            ['quickName', 'quickPacking'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            if (document.getElementById('quickConv')) document.getElementById('quickConv').value = 1;

            showToast(`Medicine "${name}" added locally (Offline ✓)`);

            const searchInput = document.getElementById('productSearch');
            if (searchInput) {
                searchInput.value = name;
                searchInput.dispatchEvent(new Event('input'));
            }
        };

        if (!navigator.onLine) {
            await handleOfflineSave();
            return;
        }

        try {
            const response = await fetch('/api/products/quick-add/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json', 
                    'X-CSRFToken': getCookie('csrftoken'),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(data)
            });
            const result = await response.json().catch(() => ({}));
            if (response.ok && result.success) {
                const onlineProd = {
                    id: result.id,
                    name: result.name || name,
                    product_name: result.name || name,
                    packing: packing,
                    product_packing: packing,
                    conversion_factor: conv,
                    tax_rate: taxRate,
                    tax_id: tax_id,
                    batches: []
                };

                if (typeof OfflineSync !== 'undefined') {
                    OfflineSync.cacheNewProduct(onlineProd);
                }
                clearPosSearchCache();

                const modalEl = document.getElementById('quickAddModal');
                if (modalEl) {
                    const modal = bootstrap.Modal.getInstance(modalEl) || bootstrap.Modal.getOrCreateInstance(modalEl);
                    modal.hide();
                }

                ['quickName', 'quickPacking'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.value = '';
                });
                if (document.getElementById('quickConv')) document.getElementById('quickConv').value = 1;

                showToast(`Medicine "${result.name || name}" added successfully`);

                const searchInput = document.getElementById('productSearch');
                if (searchInput) {
                    searchInput.value = result.name || name;
                    searchInput.dispatchEvent(new Event('input'));
                }
            } else {
                showToast('Error: ' + (result.error || 'Could not save medicine'), 'error');
            }
        } catch (err) {
            console.warn('POS Quick Add network error, saving offline:', err);
            await handleOfflineSave();
        }
    }
    window.saveQuickProduct = saveQuickProduct;

    function updateQty(index, val) {
        const item = cart[index]; const newQty = parseInt(val) || 0;
        if (newQty > 0 && newQty <= item.max_stock) {
            item.quantity = newQty;
        } else if (newQty > item.max_stock) {
            item.quantity = item.max_stock;
            alert('Stock limit reached');
        }
        // Update only the total cell of this row (avoids losing focus)
        const rows = document.querySelectorAll('#posTable tbody tr');
        if (rows[index]) {
            const total = item.price * item.quantity;
            const basePrice = item.price / (1 + item.tax_rate / 100);
            const taxAmount = (item.price - basePrice) * item.quantity;
            // Total column is 6th td (index 5)
            const totalCell = rows[index].querySelectorAll('td')[5];
            if (totalCell) totalCell.innerHTML = `₹${total.toFixed(2)}`;
            // GST/Tax column is 5th td (index 4)
            const taxCell = rows[index].querySelectorAll('td')[4];
            if (taxCell) taxCell.innerHTML = `₹${taxAmount.toFixed(2)} <span class="text-muted x-small">(${item.tax_rate}% incl.)</span>`;
        }
        calculateGrandTotal();
    }

    function calculateGrandTotal() {
        try {
            // MRP is tax-inclusive, so calculate totals correctly
            const subTotal = cart.reduce((sum, item) => {
                const price = parseFloat(item.price) || 0;
                const taxRate = parseFloat(item.tax_rate) || 0;
                const basePrice = price / (1 + taxRate / 100);
                return sum + (basePrice * (parseInt(item.quantity) || 0));
            }, 0);
            const totalTax = cart.reduce((sum, item) => {
                const price = parseFloat(item.price) || 0;
                const taxRate = parseFloat(item.tax_rate) || 0;
                const basePrice = price / (1 + taxRate / 100);
                const taxPerItem = price - basePrice;
                return sum + (taxPerItem * (parseInt(item.quantity) || 0));
            }, 0);
            
            
            const validSubTotal = isNaN(subTotal) ? 0 : subTotal;
            const validTotalTax = isNaN(totalTax) ? 0 : totalTax;
            
            const gross = validSubTotal + validTotalTax;
            const discount = parseFloat(document.getElementById('summaryDiscount').value) || 0;
            const ratio = gross > 0 ? (gross - discount) / gross : 1;
            
            const discountedSubTotal = validSubTotal * ratio;
            const discountedTotalTax = validTotalTax * ratio;
            
            let grandTotal = gross - discount;

            // Keep exact decimal total; do not force whole-rupee rounding because
            // it creates mismatches between subtotal + GST and final invoice total.
            const roundedTotal = Number(grandTotal.toFixed(2));
            const roundOff = Number((roundedTotal - grandTotal).toFixed(2));
            grandTotal = roundedTotal;

            document.getElementById('summarySubTotal').innerText = discountedSubTotal.toFixed(2);
            document.getElementById('summaryTax').innerText = discountedTotalTax.toFixed(2);
            document.getElementById('summaryGrandTotal').innerText = grandTotal.toFixed(2);

            const roundOffEl = document.getElementById('summaryRoundOff');
            if (roundOffEl) {
                roundOffEl.innerText = (roundOff >= 0 ? '+' : '') + roundOff.toFixed(2);
            }

            // Update footer counters
            const itemCount = cart.reduce((sum, item) => sum + (parseInt(item.quantity) || 0), 0);
            document.getElementById('cartItemCount').innerText = `${itemCount} item${itemCount !== 1 ? 's' : ''}`;
            document.getElementById('cartTotal').innerText = grandTotal.toFixed(2);
        } catch (e) {
            console.error("Error in calculateGrandTotal:", e);
        }
    }

    function calculateDiscount(changed) {
        const subTotal = cart.reduce((sum, item) => {
            const basePrice = item.price / (1 + item.tax_rate / 100);
            return sum + (basePrice * item.quantity);
        }, 0);
        const totalTax = cart.reduce((sum, item) => {
            const basePrice = item.price / (1 + item.tax_rate / 100);
            const taxPerItem = item.price - basePrice;
            return sum + (taxPerItem * item.quantity);
        }, 0);
        const gross = subTotal + totalTax;
        let amount = parseFloat(document.getElementById('summaryDiscount').value) || 0;
        let percent = parseFloat(document.getElementById('summaryDiscountPerc').value) || 0;

        if (changed === 'perc') {
            amount = gross * percent / 100;
            document.getElementById('summaryDiscount').value = amount.toFixed(2);
        } else {
            percent = gross > 0 ? (amount / gross) * 100 : 0;
            document.getElementById('summaryDiscountPerc').value = percent.toFixed(2);
        }

        calculateGrandTotal();
    }

    function showLoader(message = 'Please wait...') {
        const loader = document.getElementById('universalLoader');
        if (!loader) return;
        loader.querySelector('.loader-text').innerText = message;
        loader.classList.remove('d-none');
        loader.setAttribute('aria-busy', 'true');
    }

    function hideLoader() {
        const loader = document.getElementById('universalLoader');
        if (!loader) return;
        loader.classList.add('d-none');
        loader.setAttribute('aria-busy', 'false');
    }

    function clearCart() { if (confirm('Clear all?')) { cart = []; renderCart(); } }

    if (editData) {
        populateEditData(editData);
    }
    function removeFromCart(index) { cart.splice(index, 1); renderCart(); }

    // ── Payment mode highlight toggle ──
    document.querySelectorAll('input[name="paymentMethod"]').forEach(radio => {
        radio.addEventListener('change', () => {
            document.querySelectorAll('label.payment-btn').forEach(l => l.classList.remove('payment-btn-active'));
            document.querySelector(`label[for="${radio.id}"]`).classList.add('payment-btn-active');
        });
    });

    function validatePatientDetails() {
        const isCounterMode = !document.getElementById('counterSaleBanner').classList.contains('d-none');
        const paymentMethod = document.querySelector('input[name="paymentMethod"]:checked').value;
        
        if (isCounterMode && paymentMethod !== 'Credit') return true;

        const fields = [
            { id: 'patientName',    value: document.getElementById('patientName').value.trim(), required: true },
            { id: 'patientAddress', value: document.getElementById('patientAddress').value.trim(), required: !isCounterMode },
            { id: 'doctorName',     value: document.getElementById('doctorName').value.trim(), required: !isCounterMode },
        ];

        let valid = true;
        fields.forEach(f => {
            const el = document.getElementById(f.id);
            if (f.required && !f.value) {
                el.classList.add('is-invalid');
                el.addEventListener('input', () => el.classList.remove('is-invalid'), { once: true });
                valid = false;
            } else {
                el.classList.remove('is-invalid');
            }
        });

        if (!valid) {
            const first = document.querySelector('#patientName.is-invalid, #patientAddress.is-invalid, #doctorName.is-invalid');
            if (first) { first.scrollIntoView({ behavior: 'smooth', block: 'center' }); first.focus(); }
        }
        return valid;
    }

    async function completeOrder() {
        if (cart.length === 0) return alert('Bill is empty');
        if (!validatePatientDetails()) return;

        const checkoutBtn = document.querySelector('.btn-success.btn-lg');
        if (checkoutBtn) { checkoutBtn.disabled = true; }
        showLoader('Generating bill...');

        const data = {
            invoice_id: editData?.invoice_id || null,
            date: document.getElementById('billDate') ? document.getElementById('billDate').value : null,
            patient_name: document.getElementById('patientName').value,
            patient_address: document.getElementById('patientAddress').value,
            
            patient_phone: document.getElementById('patientPhone').value,
            doctor_name: document.getElementById('doctorName').value,
            payment_mode: document.querySelector('input[name="paymentMethod"]:checked').value,
            items: cart.map(item => ({
                product_id: item.id,
                batch_id: item.batch_id,
                quantity: item.quantity,
                price: item.price,
                // MRP is tax-inclusive, so total = MRP * quantity (no additional tax)
                total: item.price * item.quantity
            })),
            sub_total: parseFloat(document.getElementById('summarySubTotal').innerText),
            tax_amount: parseFloat(document.getElementById('summaryTax').innerText),
            discount_amount: parseFloat(document.getElementById('summaryDiscount').value) || 0,
            round_off: parseFloat(document.getElementById('summaryRoundOff').innerText) || 0,
            total_amount: parseFloat(document.getElementById('summaryGrandTotal').innerText),
            sale_type: !document.getElementById('counterSaleBanner').classList.contains('d-none') ? 'Counter' : 'Prescription'
        };

        try {
            if (!navigator.onLine && typeof OfflineSync !== 'undefined') {
                // Save offline & deduct stock directly from cache
                deductSoldItemsFromPosCache(data.items);
                const fakeInvoiceId = 'OFFLINE_' + Date.now();
                await OfflineSync.queueRequest(OfflineSync.salesStore, '/pos/', data, 'Sale saved offline!');
                
                // Show offline success modal
                document.getElementById('successInvoiceNum').textContent = "Pending Sync";
                document.getElementById('btnSuccessPrint').style.display = 'inline-block';
                document.getElementById('btnSuccessPrint').onclick = () => {
                    printInvoiceOffline(data);
                    setTimeout(() => resetPOS("Pending Sync*"), 500);
                };
                
                document.getElementById('btnSuccessWhatsApp').onclick = () => {
                    let phone = data.patient_phone;
                    if (!phone || phone.length < 10) {
                        phone = prompt("Enter patient's 10-digit WhatsApp number:", "");
                        if (!phone) return;
                    }
                    if(phone.length === 10) phone = '91' + phone;
                    const firmName = (pharmacyInfo.name || 'EASY PHARMA').toUpperCase();
                    let msg = `*${firmName} - INVOICE (Offline)*\n`;
                    msg += `Address: ${pharmacyInfo.address || '—'}\n`;
                    msg += `Patient: ${data.patient_name || 'Cash Customer'}\n\n`;
                    msg += `*ITEMS:*\n`;
                    cart.forEach(item => {
                        const batchExp = ` [B: ${item.batch_no || '—'}, Exp: ${item.expiry || '—'}]`;
                        msg += `- ${item.name}${batchExp} (x${item.quantity}) = ₹${(item.price * item.quantity).toFixed(2)}\n`;
                    });
                    msg += `\n*Total Amount: ₹${data.total_amount.toFixed(2)}*\n\n`;
                    msg += `Thank you for your visit!\n`;
                    window.open(`https://wa.me/${phone}?text=${encodeURIComponent(msg)}`, '_blank');
                };
                document.getElementById('btnSuccessNewSale').onclick = () => {
                    // For offline, we don't know the true next invoice number from server, 
                    // so we just append a star to indicate offline mode or leave it as pending.
                    resetPOS("Pending Sync*");
                };

                const successModalEl = document.getElementById('checkoutSuccessModal');
                const successModal = new bootstrap.Modal(successModalEl);
                successModal.show();
                
                successModalEl.addEventListener('shown.bs.modal', function () {
                    const modalButtons = [
                        document.getElementById('btnSuccessPrint'),
                        document.getElementById('btnSuccessWhatsApp'),
                        document.getElementById('btnSuccessNewSale')
                    ].filter(b => b && window.getComputedStyle(b).display !== 'none');
                    
                    if (modalButtons.length > 0) {
                        let activeBtnIndex = 0;
                        modalButtons[0].focus();
                        
                        successModalEl.onkeydown = (e) => {
                            if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                                e.preventDefault();
                                activeBtnIndex = (activeBtnIndex + 1) % modalButtons.length;
                                modalButtons[activeBtnIndex].focus();
                            } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
                                e.preventDefault();
                                activeBtnIndex = (activeBtnIndex - 1 + modalButtons.length) % modalButtons.length;
                                modalButtons[activeBtnIndex].focus();
                            }
                        };
                    }
                }, { once: true });

            } else {
                const response = await fetch('/pos/', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') }, body: JSON.stringify(data) });
                const result = await response.json();
                if (result.success) {
                    // Update in-memory & offline cache with remaining stock immediately
                    deductSoldItemsFromPosCache(data.items);
                    if (typeof OfflineSync !== 'undefined') {
                        OfflineSync.preloadProductCache();
                    }
                    // Show Success Modal instead of reloading
                    document.getElementById('successInvoiceNum').textContent = result.invoice_number;
                    
                    document.getElementById('btnSuccessPrint').style.display = 'inline-block';
                    document.getElementById('btnSuccessPrint').onclick = async () => {
                        try {
                            const directResp = await fetch(`/pos/print-direct/${result.invoice_id}/`);
                            const directRes = await directResp.json();
                            if (directRes.success) {
                                showToast(`Printing directly to "${directRes.printer}"...`, 'success');
                            } else {
                                console.warn("Direct printing failed: " + directRes.error);
                                window.open(`/pos/print/${result.invoice_id}/`, '_blank');
                            }
                        } catch (err) {
                            console.error("Direct printing request error: ", err);
                            window.open(`/pos/print/${result.invoice_id}/`, '_blank');
                        }
                        setTimeout(() => resetPOS(result.next_invoice_number), 500);
                    };
                    
                    document.getElementById('btnSuccessNewSale').onclick = () => {
                        resetPOS(result.next_invoice_number);
                    };
                    
                    document.getElementById('btnSuccessWhatsApp').onclick = () => {
                        let phone = data.patient_phone;
                        if (!phone || phone.length < 10) {
                            phone = prompt("Enter patient's 10-digit WhatsApp number:", "");
                            if (!phone) return;
                        }
                        if(phone.length === 10) phone = '91' + phone;
                        
                        const firmName = (pharmacyInfo.name || 'EASY PHARMA').toUpperCase();
                        let msg = `*${firmName} - INVOICE*\n`;
                        msg += `Address: ${pharmacyInfo.address || '—'}\n`;
                        msg += `Invoice No: ${result.invoice_number}\n`;
                        msg += `Name: ${data.patient_name || 'Cash Customer'}\n\n`;
                        
                        msg += `*ITEMS:*\n`;
                        cart.forEach(item => {
                            const batchExp = ` [B: ${item.batch_no || '—'}, Exp: ${item.expiry || '—'}]`;
                            msg += `- ${item.name}${batchExp} (x${item.quantity}) = ₹${(item.price * item.quantity).toFixed(2)}\n`;
                        });
                        msg += `\n*Total Amount: ₹${data.total_amount.toFixed(2)}*\n\n`;
                        msg += `Thank you for your visit!\n`;
                        
                        window.open(`https://wa.me/${phone}?text=${encodeURIComponent(msg)}`, '_blank');
                    };

                    const successModalEl = document.getElementById('checkoutSuccessModal');
                    const successModal = new bootstrap.Modal(successModalEl);
                    successModal.show();
                    
                    // Keyboard navigation for success modal
                    successModalEl.addEventListener('shown.bs.modal', function () {
                        const modalButtons = [
                            document.getElementById('btnSuccessPrint'),
                            document.getElementById('btnSuccessWhatsApp'),
                            document.getElementById('btnSuccessNewSale')
                        ].filter(b => b && window.getComputedStyle(b).display !== 'none');
                        
                        if (modalButtons.length > 0) {
                            let activeBtnIndex = 0;
                            modalButtons[0].focus();
                            
                            successModalEl.onkeydown = (e) => {
                                if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                                    e.preventDefault();
                                    activeBtnIndex = (activeBtnIndex + 1) % modalButtons.length;
                                    modalButtons[activeBtnIndex].focus();
                                } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
                                    e.preventDefault();
                                    activeBtnIndex = (activeBtnIndex - 1 + modalButtons.length) % modalButtons.length;
                                    modalButtons[activeBtnIndex].focus();
                                }
                            };
                        }
                    }, { once: true });
                } else if (result.queued) {
                    // Service Worker queued it offline & update cache stock
                    deductSoldItemsFromPosCache(data.items);
                    document.getElementById('successInvoiceNum').textContent = "Pending Sync";
                    document.getElementById('btnSuccessPrint').style.display = 'inline-block';
                    document.getElementById('btnSuccessPrint').onclick = () => {
                        printInvoiceOffline(data);
                        setTimeout(() => resetPOS("Pending Sync*"), 500);
                    };
                    
                    document.getElementById('btnSuccessWhatsApp').onclick = () => {
                        let phone = data.patient_phone;
                        if (!phone || phone.length < 10) {
                            phone = prompt("Enter patient's 10-digit WhatsApp number:", "");
                            if (!phone) return;
                        }
                        if(phone.length === 10) phone = '91' + phone;
                        const firmName = (pharmacyInfo.name || 'EASY PHARMA').toUpperCase();
                        let msg = `*${firmName} - INVOICE (Offline)*\n`;
                        msg += `Name: ${data.patient_name || 'Cash Customer'}\n\n`;
                        msg += `*ITEMS:*\n`;
                        cart.forEach(item => {
                            const batchExp = ` [B: ${item.batch_no || '—'}, Exp: ${item.expiry || '—'}]`;
                            msg += `- ${item.name}${batchExp} (x${item.quantity}) = ₹${(item.price * item.quantity).toFixed(2)}\n`;
                        });
                        msg += `\n*Total Amount: ₹${data.total_amount.toFixed(2)}*\n\n`;
                        msg += `Thank you for your visit!\n`;
                        window.open(`https://wa.me/${phone}?text=${encodeURIComponent(msg)}`, '_blank');
                    };
                    document.getElementById('btnSuccessNewSale').onclick = () => {
                        resetPOS("Pending Sync*");
                    };

                    const successModalEl = document.getElementById('checkoutSuccessModal');
                    const successModal = new bootstrap.Modal(successModalEl);
                    successModal.show();
                } else {
                    alert('Error: ' + result.error);
                }
            }
        } catch (err) {
            alert('Error loader: ' + err.message);
        } finally {
            hideLoader();
            if (checkoutBtn) { checkoutBtn.disabled = false; }
        }
    }

        // Multi-Bill State Management
let bills = [{
    id: Date.now(),
    cart: [],
    patient: { name: '', address: '', phone: '', doctor: '' },
    active: true
}];
let activeBillIndex = 0;

// ── POS Draft Auto-Save & Recovery ──
function savePosDraft() {
    if (typeof editData !== 'undefined' && editData) return;
    try {
        if (typeof saveCurrentState === 'function') {
            saveCurrentState();
        }
        const hasData = bills.some(b => b.cart && b.cart.length > 0) ||
                        bills.some(b => b.patient && (b.patient.name || b.patient.phone || b.patient.doctor));
        if (hasData) {
            const draft = {
                bills: bills,
                activeBillIndex: activeBillIndex,
                timestamp: Date.now()
            };
            localStorage.setItem('easypharma_pos_draft_v1', JSON.stringify(draft));
        } else {
            localStorage.removeItem('easypharma_pos_draft_v1');
        }
    } catch (e) {
        console.warn('Failed to save POS draft', e);
    }
}

function clearPosDraft() {
    try {
        localStorage.removeItem('easypharma_pos_draft_v1');
    } catch (e) {}
}

function restorePosDraft() {
    if (typeof editData !== 'undefined' && editData) return;
    try {
        const raw = localStorage.getItem('easypharma_pos_draft_v1');
        if (!raw) return;
        const draft = JSON.parse(raw);
        if (draft && Array.isArray(draft.bills) && draft.bills.length > 0) {
            const hasData = draft.bills.some(b => b.cart && b.cart.length > 0) ||
                            draft.bills.some(b => b.patient && (b.patient.name || b.patient.phone || b.patient.doctor));
            if (hasData) {
                bills = draft.bills;
                activeBillIndex = typeof draft.activeBillIndex === 'number' && draft.activeBillIndex < bills.length ? draft.activeBillIndex : 0;
                loadBillState(activeBillIndex);
                updateBillTabsUI();
                showToast('⚡ Restored unsaved bill from previous session! <button type="button" class="btn btn-sm btn-outline-light ms-2" onclick="clearPosDraftAndReset()" style="padding:1px 6px;font-size:11px;">Clear Draft</button>', 'info');
            }
        }
    } catch (e) {
        console.warn('Failed to restore POS draft', e);
    }
}

function getCurrentBillDate() {
    const today = new Date();
    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function setCurrentBillDate() {
    if (typeof editData !== 'undefined' && editData) return;
    const billDate = document.getElementById('billDate');
    if (billDate) billDate.value = getCurrentBillDate();
}

window.clearPosDraftAndReset = function() {
    clearPosDraft();
    bills = [{
        id: Date.now(),
        cart: [],
        patient: { name: '', address: '', phone: '', doctor: '' },
        active: true
    }];
    activeBillIndex = 0;
    loadBillState(0);
    updateBillTabsUI();
    showToast('Draft cleared', 'warning');
};

function updateBillTabsUI() {
    const container = document.getElementById('billTabsContainer');
    if (!container) return;
    container.innerHTML = '';
    
    bills.forEach((bill, index) => {
        const isActive = index === activeBillIndex;
        const tab = document.createElement('button');
        tab.className = `btn ${isActive ? 'btn-primary' : 'btn-outline-secondary'} btn-sm d-flex align-items-center`;
        tab.style.minWidth = "120px";
        tab.innerHTML = `
            <span onclick="switchBill(${index})" class="flex-grow-1 text-truncate">Bill ${index + 1} ${bill.patient.name ? '- ' + bill.patient.name : ''}</span>
            ${bills.length > 1 ? `<i class="fas fa-times ms-2 text-danger" onclick="closeBill(${index}, event)"></i>` : ''}
        `;
        container.appendChild(tab);
    });

    // Add "New Bill" button
    const addBtn = document.createElement('button');
    addBtn.className = "btn btn-success btn-sm";
    addBtn.innerHTML = '<i class="fas fa-plus"></i> New (F1)';
    addBtn.onclick = addNewBill;
    container.appendChild(addBtn);
}

function addNewBill() {
    // Current bill ko save karein pehle
    saveCurrentState();
    
    // Naya bill object banayein
    const newBill = {
        id: Date.now(),
        cart: [],
        patient: { name: '', address: '', phone: '', doctor: '' },
        active: true
    };
    bills.push(newBill);
    activeBillIndex = bills.length - 1;
    
    loadBillState(activeBillIndex);
    updateBillTabsUI();
    savePosDraft();
}

    function saveCurrentState() {
        if (!bills[activeBillIndex]) return;
        bills[activeBillIndex].cart = [...cart];
        bills[activeBillIndex].patient = {
            name: document.getElementById('patientName') ? document.getElementById('patientName').value : '',
            address: document.getElementById('patientAddress') ? document.getElementById('patientAddress').value : '',
            phone: document.getElementById('patientPhone') ? document.getElementById('patientPhone').value : '',
            doctor: document.getElementById('doctorName') ? document.getElementById('doctorName').value : ''
        };
    }

    function loadBillState(index) {
        if (!bills[index]) return;
        const bill = bills[index];
        cart = [...bill.cart];
        if (document.getElementById('patientName')) document.getElementById('patientName').value = bill.patient.name || '';
        if (document.getElementById('patientAddress')) document.getElementById('patientAddress').value = bill.patient.address || '';
        if (document.getElementById('patientPhone')) document.getElementById('patientPhone').value = bill.patient.phone || '';
        if (document.getElementById('doctorName')) document.getElementById('doctorName').value = bill.patient.doctor || '';
        
        renderCart(); 
    }

    function switchBill(index) {
        saveCurrentState();
        savePosDraft();
        activeBillIndex = index;
        loadBillState(index);
        updateBillTabsUI();
    }

    function closeBill(index, event) {
        event.stopPropagation();
        if (confirm("Close this bill? Data will be lost.")) {
            bills.splice(index, 1);
            if (activeBillIndex >= bills.length) activeBillIndex = bills.length - 1;
            loadBillState(activeBillIndex);
            updateBillTabsUI();
            savePosDraft();
        }
    }

    // F1 Key Listener
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F1') {
            e.preventDefault();
            addNewBill();
        }
    });

    // Auto-save listeners on patient input fields
    document.addEventListener('DOMContentLoaded', function() {
        ['patientName', 'patientAddress', 'patientPhone', 'doctorName', 'summaryDiscount', 'summaryDiscountPerc', 'billDate'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', () => {
                    saveCurrentState();
                    savePosDraft();
                });
                el.addEventListener('change', () => {
                    saveCurrentState();
                    savePosDraft();
                });
            }
        });
    });

    // Initialize
    window.addEventListener('load', () => {
        setCurrentBillDate();
        if (!editData) {
            restorePosDraft();
        }
        updateBillTabsUI();
    });

    // Warn on accidental refresh or close if bill has items
    window.addEventListener('beforeunload', function(e) {
        if (window.__isOrderSubmitting) return;
        savePosDraft();
        const hasUnsaved = bills.some(b => b.cart && b.cart.length > 0);
        if (hasUnsaved) {
            e.preventDefault();
            e.returnValue = 'You have unsaved items in your bill. Are you sure you want to leave or refresh?';
            return e.returnValue;
        }
    });

    function resetPOS(nextInvNum) {
        clearPosDraft();
        if (typeof editData !== 'undefined' && editData) {
            window.location.href = '/pos/list/';
            return;
        }

        const successModalEl = document.getElementById('checkoutSuccessModal');
        const modal = bootstrap.Modal.getInstance(successModalEl);
        if(modal) modal.hide();

        cart = [];
        mrpEditMode = false;
        bills = [{
            id: Date.now(),
            cart: [],
            patient: { name: '', address: '', phone: '', doctor: '' },
            active: true
        }];
        activeBillIndex = 0;
        updateBillTabsUI();
        renderCart();
        
        const billDateEl = document.getElementById('billDate');
        if (billDateEl) {
            billDateEl.value = getCurrentBillDate();
        }
        document.getElementById('patientName').value = '';
        const isCounterMode = !document.getElementById('counterSaleBanner').classList.contains('d-none');
        document.getElementById('patientAddress').value = isCounterMode ? 'COUNTER' : tenantCity;
        document.getElementById('patientPhone').value = '';
        document.getElementById('doctorName').value = '';
        document.getElementById('summaryDiscount').value = '0';
        document.getElementById('summaryDiscountPerc').value = '0';
        document.getElementById('patientName').classList.remove('is-invalid');
        document.getElementById('patientPhone').classList.remove('is-invalid');
        
        if (nextInvNum) {
            document.getElementById('runningBillNumber').textContent = nextInvNum;
        }

        setTimeout(() => document.getElementById('productSearch').focus(), 300);
    }

    // ────────────────────────────────────────────────────────
    // AI PRESCRIPTION SCANNER LOGIC
    // ────────────────────────────────────────────────────────
    let currentStep = 1;
    let prescriptionFile = null;
    let cameraStreamObj = null;
    let currentScanResults = [];

    const scanModal = document.getElementById('scanPrescriptionModal');
    if (scanModal) {
        scanModal.addEventListener('hidden.bs.modal', function () {
            stopCamera();
            resetScanModal();
        });
    }

    const dropzone = document.getElementById('dropzone');
    const imageInput = document.getElementById('prescriptionImageInput');
    const startCameraBtn = document.getElementById('startCameraBtn');
    const captureBtn = document.getElementById('captureBtn');
    const cameraStream = document.getElementById('cameraStream');
    const previewPlaceholder = document.getElementById('previewPlaceholder');
    const previewImg = document.getElementById('prescriptionPreviewImg');
    const nextStepBtn = document.getElementById('nextStepBtn');
    const prevStepBtn = document.getElementById('prevStepBtn');
    const applyCartBtn = document.getElementById('applyCartBtn');

    if (imageInput) {
        imageInput.addEventListener('change', function(e) {
            if (e.target.files.length > 0) {
                handleSelectedFile(e.target.files[0]);
            }
        });
    }

    if (dropzone) {
        dropzone.addEventListener('dragover', function(e) {
            e.preventDefault();
            dropzone.style.backgroundColor = 'var(--brand-tint)';
            dropzone.style.borderColor = 'var(--brand)';
        });

        dropzone.addEventListener('dragleave', function(e) {
            e.preventDefault();
            dropzone.style.backgroundColor = '';
            dropzone.style.borderColor = '';
        });

        dropzone.addEventListener('drop', function(e) {
            e.preventDefault();
            dropzone.style.backgroundColor = '';
            dropzone.style.borderColor = '';
            if (e.dataTransfer.files.length > 0) {
                handleSelectedFile(e.dataTransfer.files[0]);
            }
        });
    }

    if (startCameraBtn) {
        startCameraBtn.addEventListener('click', async function() {
            try {
                stopCamera();
                previewPlaceholder.classList.add('d-none');
                previewImg.classList.add('d-none');
                cameraStream.classList.remove('d-none');
                captureBtn.classList.remove('d-none');

                cameraStreamObj = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: 'environment' }
                });
                cameraStream.srcObject = cameraStreamObj;
            } catch (err) {
                alert('Could not access camera: ' + err.message);
                resetScanModal();
            }
        });
    }

    if (captureBtn) {
        captureBtn.addEventListener('click', function() {
            if (!cameraStreamObj) return;

            const canvas = document.createElement('canvas');
            canvas.width = cameraStream.videoWidth || 640;
            canvas.height = cameraStream.videoHeight || 480;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(cameraStream, 0, 0, canvas.width, canvas.height);

            canvas.toBlob(function(blob) {
                const file = new File([blob], "captured_prescription.jpg", { type: "image/jpeg" });
                handleSelectedFile(file);
                stopCamera();
            }, 'image/jpeg', 0.95);
        });
    }

    function stopCamera() {
        if (cameraStreamObj) {
            cameraStreamObj.getTracks().forEach(track => track.stop());
            cameraStreamObj = null;
        }
        if (cameraStream) {
            cameraStream.srcObject = null;
            cameraStream.classList.add('d-none');
        }
        if (captureBtn) {
            captureBtn.classList.add('d-none');
        }
    }

    function handleSelectedFile(file) {
        prescriptionFile = file;
        
        // Show preview
        const reader = new FileReader();
        reader.onload = function(e) {
            previewPlaceholder.classList.add('d-none');
            cameraStream.classList.add('d-none');
            captureBtn.classList.add('d-none');
            
            previewImg.src = e.target.result;
            previewImg.classList.remove('d-none');
            
            // Set for reference in Step 2
            document.getElementById('prescriptionRefImg').src = e.target.result;
        };
        reader.readAsDataURL(file);
    }

    function resetScanModal() {
        currentStep = 1;
        prescriptionFile = null;
        currentScanResults = [];
        if (previewImg) {
            previewImg.src = '';
            previewImg.classList.add('d-none');
        }
        if (previewPlaceholder) {
            previewPlaceholder.classList.remove('d-none');
        }
        document.getElementById('prescriptionRefImg').src = '';
        document.getElementById('matchingTableBody').innerHTML = '';
        document.getElementById('scanPatientName').value = '';
        document.getElementById('scanPatientPhone').value = '';
        document.getElementById('scanDoctorName').value = '';
        showStep(1);
    }

    function showStep(step) {
        currentStep = step;
        
        // Toggle contents
        document.querySelectorAll('.step-content').forEach(el => el.classList.add('d-none'));
        document.getElementById('scanLoader').classList.add('d-none');
        document.getElementById('stepContent' + step).classList.remove('d-none');
        
        // Update indicators
        for (let i = 1; i <= 3; i++) {
            const ind = document.getElementById('stepIndicator' + i);
            const num = ind.querySelector('.step-number');
            if (i === step) {
                ind.classList.remove('text-muted');
                ind.classList.add('active');
                num.classList.remove('bg-secondary');
                num.classList.add('bg-primary');
            } else if (i < step) {
                ind.classList.remove('text-muted', 'active');
                num.classList.remove('bg-secondary', 'bg-primary');
                num.classList.add('bg-success');
            } else {
                ind.classList.add('text-muted');
                ind.classList.remove('active');
                num.classList.remove('bg-primary', 'bg-success');
                num.classList.add('bg-secondary');
            }
        }
        
        // Update buttons
        prevStepBtn.disabled = step === 1;
        
        if (step === 1) {
            nextStepBtn.innerText = 'Scan & Next';
            nextStepBtn.classList.remove('d-none');
            applyCartBtn.classList.add('d-none');
        } else if (step === 2) {
            nextStepBtn.innerText = 'Next';
            nextStepBtn.classList.remove('d-none');
            applyCartBtn.classList.add('d-none');
        } else if (step === 3) {
            nextStepBtn.classList.add('d-none');
            applyCartBtn.classList.remove('d-none');
        }
    }

    if (prevStepBtn) {
        prevStepBtn.addEventListener('click', function() {
            if (currentStep > 1) {
                showStep(currentStep - 1);
            }
        });
    }

    if (nextStepBtn) {
        nextStepBtn.addEventListener('click', function() {
            if (currentStep === 1) {
                if (!prescriptionFile) {
                    alert('Please select or capture a prescription image first.');
                    return;
                }
                uploadAndScanPrescription();
            } else if (currentStep === 2) {
                showStep(3);
            }
        });
    }

    function compressImage(file, callback) {
        const reader = new FileReader();
        reader.readAsDataURL(file);
        reader.onload = function(event) {
            const img = new Image();
            img.src = event.target.result;
            img.onload = function() {
                const maxDim = 1024;
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
                }, 'image/jpeg', 0.75);
            };
        };
    }

    function uploadAndScanPrescription() {
        // Hide Step 1 and show loader
        document.getElementById('stepContent1').classList.add('d-none');
        const loader = document.getElementById('scanLoader');
        loader.classList.remove('d-none');
        
        nextStepBtn.classList.add('d-none');
        prevStepBtn.disabled = true;

        compressImage(prescriptionFile, function(compressedBlob) {
            const formData = new FormData();
            formData.append('prescription_image', compressedBlob, 'scan.jpg');

            fetch('/api/pos/scan-prescription/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': getCookie('csrftoken')
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('scansTodayCount').innerText = data.scans_today;
                    document.getElementById('maxScansCount').innerText = data.max_scans;
                    
                    document.getElementById('scanPatientName').value = data.patient_name || '';
                    document.getElementById('scanPatientPhone').value = data.patient_phone || '';
                    document.getElementById('scanDoctorName').value = data.doctor_name || '';
                    
                    renderMatchingTable(data.results);
                    showStep(2);
                } else {
                    alert(data.error || 'Failed to scan prescription.');
                    showStep(1);
                }
            })
            .catch(err => {
                alert('Error scanning prescription: ' + err.message);
                showStep(1);
            });
        });
    }

    function renderMatchingTable(results) {
        const tbody = document.getElementById('matchingTableBody');
        tbody.innerHTML = '';
        currentScanResults = results;
        
        if (results.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="text-center py-4 text-muted">No medicines could be extracted.</td></tr>`;
            return;
        }
        
        results.forEach((row, rowIndex) => {
            const tr = document.createElement('tr');
            tr.dataset.rowIndex = rowIndex;
            
            let productOptionsHtml = '';
            if (row.matches && row.matches.length > 0) {
                row.matches.forEach((p, pIndex) => {
                    const isSelected = pIndex === 0 ? 'selected' : '';
                    productOptionsHtml += `<option value="${p.id}" data-index="${pIndex}" ${isSelected}>${p.name} (${p.packing || 'N/A'}) - ${p.company || 'Unknown'}</option>`;
                });
            } else {
                productOptionsHtml += `<option value="" selected>⚠️ No match found in stock</option>`;
            }
            // Append Search option
            productOptionsHtml += `<option value="__search__">🔍 Search another product...</option>`;
            
            let batchOptionsHtml = '';
            const bestProduct = row.best_match;
            if (bestProduct && bestProduct.batches && bestProduct.batches.length > 0) {
                bestProduct.batches.forEach((b, bIndex) => {
                    const expired = isExpired(b.expiry);
                    const isSelected = (bIndex === 0 && !expired) ? 'selected' : '';
                    const disabledAttr = expired ? 'disabled style="color: #dc3545;"' : '';
                    batchOptionsHtml += `<option value="${b.batch_id}" data-price="${b.price}" data-batch-no="${b.batch_no}" data-expiry="${b.expiry}" data-stock="${b.stock}" ${isSelected} ${disabledAttr}>${b.batch_no} (Exp: ${b.expiry}${expired ? ' - EXPIRED' : ''}, Stock: ${b.stock})</option>`;
                });
            } else {
                batchOptionsHtml += `<option value="">No Batch</option>`;
            }
            
            const isOutOfStock = !bestProduct || !bestProduct.batches || bestProduct.batches.length === 0;
            
            tr.innerHTML = `
                <td class="ps-3">
                    <span class="fw-bold small text-dark">${row.scanned_name}</span>
                </td>
                <td>
                    <select class="form-select form-select-sm product-match-select" onchange="onMatchedProductChange(this, ${rowIndex})">
                        ${productOptionsHtml}
                    </select>
                </td>
                <td>
                    <select class="form-select form-select-sm batch-match-select" ${isOutOfStock ? 'disabled' : ''}>
                        ${batchOptionsHtml}
                    </select>
                </td>
                <td>
                    <input type="number" class="form-control form-control-sm qty-match-input" value="${row.scanned_qty}" min="1" style="width: 70px;">
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    window.onMatchedProductChange = function(selectElem, rowIndex) {
        const productIndex = selectElem.selectedIndex;
        const selectedOption = selectElem.options[productIndex];
        
        // Handle database manual search option
        if (selectElem.value === '__search__') {
            const query = prompt("Search inventory for a product/substitute:");
            if (!query) {
                // Reset select to first option
                selectElem.selectedIndex = 0;
                onMatchedProductChange(selectElem, rowIndex);
                return;
            }
            
            selectElem.innerHTML = `<option value="">Searching...</option>`;
            
            fetch(`/api/products/search/?q=${encodeURIComponent(query)}`)
            .then(res => res.json())
            .then(products => {
                let optionsHtml = '';
                if (products && products.length > 0) {
                    currentScanResults[rowIndex].matches = products;
                    products.forEach((p, pIndex) => {
                        optionsHtml += `<option value="${p.id}" data-index="${pIndex}">${p.name} (${p.packing || 'N/A'}) - Stock: ${p.batches.reduce((acc, b) => acc + b.stock, 0)}</option>`;
                    });
                } else {
                    optionsHtml += `<option value="" selected>⚠️ No match found in stock</option>`;
                }
                optionsHtml += `<option value="__search__">🔍 Search another product...</option>`;
                selectElem.innerHTML = optionsHtml;
                
                selectElem.selectedIndex = 0;
                onMatchedProductChange(selectElem, rowIndex);
            })
            .catch(err => {
                alert('Search failed: ' + err.message);
                selectElem.selectedIndex = 0;
                onMatchedProductChange(selectElem, rowIndex);
            });
            return;
        }
        
        const pIndex = parseInt(selectedOption.dataset.index);
        const row = currentScanResults[rowIndex];
        
        const tr = selectElem.closest('tr');
        const batchSelect = tr.querySelector('.batch-match-select');
        
        if (isNaN(pIndex) || !row.matches[pIndex]) {
            batchSelect.innerHTML = '<option value="">No Batch</option>';
            batchSelect.disabled = true;
            return;
        }
        
        const product = row.matches[pIndex];
        let batchOptionsHtml = '';
        if (product.batches && product.batches.length > 0) {
            product.batches.forEach((b, bIndex) => {
                const expired = isExpired(b.expiry);
                const isSelected = (bIndex === 0 && !expired) ? 'selected' : '';
                const disabledAttr = expired ? 'disabled style="color: #dc3545;"' : '';
                batchOptionsHtml += `<option value="${b.batch_id}" data-price="${b.price}" data-batch-no="${b.batch_no}" data-expiry="${b.expiry}" data-stock="${b.stock}" ${isSelected} ${disabledAttr}>${b.batch_no} (Exp: ${b.expiry}${expired ? ' - EXPIRED' : ''}, Stock: ${b.stock})</option>`;
            });
            batchSelect.disabled = false;
        } else {
            batchOptionsHtml += '<option value="">No Batch</option>';
            batchSelect.disabled = true;
        }
        batchSelect.innerHTML = batchOptionsHtml;
    };

    if (applyCartBtn) {
        applyCartBtn.addEventListener('click', function() {
            const rows = document.querySelectorAll('#matchingTableBody tr');
            const itemsToAdd = [];
            
            rows.forEach(tr => {
                const rowIndex = parseInt(tr.dataset.rowIndex);
                if (isNaN(rowIndex)) return;
                
                const productSelect = tr.querySelector('.product-match-select');
                const batchSelect = tr.querySelector('.batch-match-select');
                const qtyInput = tr.querySelector('.qty-match-input');
                
                if (!productSelect || !batchSelect || !qtyInput) return;
                
                const productId = productSelect.value;
                const batchId = batchSelect.value;
                const qty = parseInt(qtyInput.value);
                
                if (!productId || !batchId || isNaN(qty) || qty <= 0) return;
                
                const selectedProductOption = productSelect.options[productSelect.selectedIndex];
                const selectedBatchOption = batchSelect.options[batchSelect.selectedIndex];
                
                const pIndex = parseInt(selectedProductOption.dataset.index);
                const row = currentScanResults[rowIndex];
                const product = row.matches[pIndex];
                
                const price = parseFloat(selectedBatchOption.dataset.price);
                const batchNo = selectedBatchOption.dataset.batchNo;
                const expiry = selectedBatchOption.dataset.expiry;
                const stock = parseInt(selectedBatchOption.dataset.stock);
                
                itemsToAdd.push({
                    id: parseInt(productId),
                    batch_id: parseInt(batchId),
                    name: product.name,
                    batch_no: batchNo,
                    expiry: expiry,
                    price: price,
                    tax_rate: parseFloat(product.tax_rate),
                    quantity: qty,
                    stock: stock
                });
            });
            
            let expiredAlerted = false;
            // Add items to POS cart
            itemsToAdd.forEach(item => {
                if (isExpired(item.expiry)) {
                    if (!expiredAlerted) {
                        alert(`Some matched items in the prescription (like "${item.name}") are EXPIRED in your stock and cannot be added to the sale!`);
                        expiredAlerted = true;
                    }
                    return;
                }
                const existing = cart.find(
                    cartItem => cartItem.id === item.id && cartItem.batch_id === item.batch_id
                );
                if (existing) {
                    existing.quantity += item.quantity;
                } else {
                    cart.push({
                        id: item.id,
                        batch_id: item.batch_id,
                        name: item.name,
                        batch_no: item.batch_no,
                        expiry: item.expiry,
                        price: item.price,
                        tax_rate: item.tax_rate,
                        quantity: item.quantity,
                        max_stock: item.stock
                    });
                }
            });
            
            // Auto fill patient info on the main POS form
            document.getElementById('patientName').value = document.getElementById('scanPatientName').value || 'CASH CUSTOMER';
            document.getElementById('patientPhone').value = document.getElementById('scanPatientPhone').value || '';
            document.getElementById('doctorName').value = document.getElementById('scanDoctorName').value || 'Self';
            document.getElementById('patientAddress').value = 'Prescription Scan';
            
            // Dispatch input and change events to ensure all handlers capture the updates
            ['patientName', 'patientPhone', 'doctorName', 'patientAddress'].forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });

            // Sync with Multi-Bill Tab System
            saveCurrentState();
            updateBillTabsUI();
            
            // Render the cart rows and calculate totals
            renderCart();
            calculateGrandTotal();
            
            // Close modal
            const bootstrapModal = bootstrap.Modal.getInstance(scanModal);
            if (bootstrapModal) {
                bootstrapModal.hide();
            }
            
            if (itemsToAdd.length > 0) {
                showToast('AI prescription items and patient details loaded into bill.', 'success');
            } else {
                showToast('Patient & doctor details loaded. (No items matched stock to add to cart)', 'info');
            }
        });
    }

