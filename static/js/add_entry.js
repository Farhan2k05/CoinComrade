document.addEventListener('DOMContentLoaded', function () {

    var dateInput = document.getElementById('date-input');
    if (dateInput && !dateInput.value) {
        dateInput.value = new Date().toISOString().split('T')[0];
    }

    var checkBox = document.getElementById('recur-check');
    var panel = document.getElementById('recur-options');
    if (checkBox && panel) {
        checkBox.addEventListener('change', function () {
            panel.style.display = this.checked ? 'block' : 'none';
        });
    }

    var typeSelect = document.getElementById('type-select');
    var categoryRow = document.getElementById('category-row');
    if (typeSelect && categoryRow) {
        typeSelect.addEventListener('change', function () {
            categoryRow.style.display = this.value === 'income' ? 'none' : 'block';
        });
    }

});