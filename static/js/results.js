let formReady = false;

window.addEventListener('beforeunload', function(e) {
    if (formReady) {
        e.preventDefault();
        e.returnValue = '';
    }
});

document.addEventListener('submit', function(e) {
    formReady = false;
});

document.addEventListener('click', function(e) {
    if (!formReady) return;
    const link = e.target.closest('a');
    if (link && link.href) {
        e.preventDefault();
        if (confirm('If you leave this page your scanned items will not be saved. Are you sure you want to leave?')) {
            formReady = false;
            window.location.href = link.href;
        }
    }
});

function pollResults(jobId) {
    fetch('/get-results/' + jobId)
        .then(r => r.json())
        .then(data => {
            if (data.status === 'complete') {
                document.getElementById('loading').style.display = 'none';
                renderForm(data);
                formReady = true;
            } else if (data.status === 'error') {
                document.getElementById('loading').innerHTML =
                    '<p class="error-text">Error processing receipt. Please try again.</p>';
            } else {
                setTimeout(function() { pollResults(jobId); }, 2000);
            }
        })
        .catch(function() {
            setTimeout(function() { pollResults(jobId); }, 3000);
        });
}

function renderForm(data) {
    const container = document.getElementById('results-area');
    let html = '<form action="/finalize" method="POST">';
    html += '<input type="hidden" name="filename" value="' + data.filename + '">';
    html += '<input type="hidden" name="receipt_date" value="' + data.receipt_date + '">';

    html += '<div class="table-wrapper"><table class="transaction-table"><thead><tr>';
    html += '<th>Item</th><th>Cost (£)</th><th>Category</th><th>Delete?</th>';
    html += '</tr></thead><tbody>';

    data.items.forEach(function (item, index) {
        const cats = data.categories_list.map(function (cat) {
            return '<option value="' + cat + '"' + (cat === item.Category ? ' selected' : '') + '>' + cat + '</option>';
        }).join('');

        html += '<tr>';
        html += '<td>'
            + '<input type="text" name="item-name-' + index + '" value="' + escHtml(item.Item) + '">'
            + '<input type="hidden" name="raw-ocr-' + index + '" value="' + escHtml(item.Raw_OCR || '') + '">'
            + '</td>';
        html += '<td><input type="number" step="0.01" min="0" name="cost-' + index + '" value="' + item.Cost + '"></td>';
        html += '<td><select name="category-' + index + '">' + cats + '</select></td>';
        html += '<td class="text-center"><input type="checkbox" name="delete-' + index + '"></td>';
        html += '</tr>';
    });

    html += '</tbody></table></div>';
    html += '<div style="display:flex; gap:1rem; margin-top:1rem;">';
    html += '<button type="submit" class="btn">Save All Transactions</button>';
    html += '<button type="button" class="btn btn-secondary" onclick="cancelReceipt()">Cancel</button>';
    html += '</div>';
    html += '</form>';
    container.innerHTML = html;
}

function cancelReceipt() {
    if (confirm('If you cancel your scanned items will not be saved. Are you sure?')) {
        formReady = false;
        window.location.href = '/';
    }
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}