// ✅ Helper to get CSRF token from cookies
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let cookie of cookies) {
            cookie = cookie.trim();
            if (cookie.startsWith(name + "=")) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// ✅ Enable edit mode
function enableEdit(id) {
    document.getElementById(`name-display-${id}`).classList.add("d-none");
    document.getElementById(`name-input-${id}`).classList.remove("d-none");
    document.getElementById(`edit-btn-${id}`).classList.add("d-none");
    document.getElementById(`save-btn-${id}`).classList.remove("d-none");
}

function saveEdit(id) {
    const newName = document.getElementById(`name-input-${id}`).value;

    fetch("/show-all-product-types/", {
        method: "PATCH",
        headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ id: id, name: newName }),
    })
    .then(response => {
        // Check if response is JSON
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            return response.json();
        } else {
            // Handle HTML response (likely an error page)
            return response.text().then(text => {
                throw new Error("Server returned HTML instead of JSON");
            });
        }
    })
    .then(data => {
        if (data.success) {
            alert(data.success);
            document.getElementById(`name-display-${id}`).textContent = newName;

            // Switch back to display mode
            document.getElementById(`name-display-${id}`).classList.remove("d-none");
            document.getElementById(`name-input-${id}`).classList.add("d-none");
            document.getElementById(`edit-btn-${id}`).classList.remove("d-none");
            document.getElementById(`save-btn-${id}`).classList.add("d-none");
        } else {
            alert("Error: " + data.error);
        }
    })
    .catch(error => {
        console.error("Error:", error);
        alert("Something went wrong while updating!");
    });
}

// ✅ Delete Product Type via Fetch API
function deleteProductType(productTypeId) {
    if (!confirm("Are you sure you want to delete this product type?")) {
        return;
    }

    fetch("/show-all-product-types/", {
        method: "DELETE",
        headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest", // Added this header
        },
        body: JSON.stringify({ id: productTypeId }),
    })
    .then(response => {
        // Check if response is JSON
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            return response.json();
        } else {
            // Handle HTML response (likely an error page)
            return response.text().then(text => {
                throw new Error("Server returned HTML instead of JSON");
            });
        }
    })
    .then(data => {
        console.log("Delete request sent for Product Type ID:", productTypeId);
        if (data.success) {
            alert("Product type deleted successfully.");
            document.getElementById(`row-${productTypeId}`).remove();
        } else {
            alert("Error: " + (data.error || "Unable to delete"));
        }
    })
    .catch(error => {
        console.error("Error:", error);
        alert("Something went wrong!");
    });
}