document.addEventListener('DOMContentLoaded', function () {
    var modal = document.getElementById('editModal');
    var closeBtn = document.querySelector('.close');

    document.querySelectorAll('.edit-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            document.getElementById('edit-id').value = this.dataset.id;
            document.getElementById('edit-name-display').textContent = this.dataset.name;
            document.getElementById('edit-name').value = this.dataset.name;
            document.getElementById('edit-amount').value = this.dataset.amount;
            document.getElementById('edit-freq').value = this.dataset.freq;
            document.getElementById('edit-category').value = this.dataset.category || '';
            document.getElementById('edit-end').value = this.dataset.end || '';
            modal.style.display = 'block';
        });
    });

    if (closeBtn) {
        closeBtn.addEventListener('click', function () {
            modal.style.display = 'none';
        });
    }

    window.addEventListener('click', function (e) {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    });
});