document.addEventListener('DOMContentLoaded', function () {

    document.querySelectorAll('.delete-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var form = this.closest('form');

            if (form.querySelector('.confirm-yes')) return;

            btn.style.display = 'none';

            var label = document.createElement('span');
            label.textContent = 'Sure? ';
            label.className = 'confirm-label';

            var yes = document.createElement('button');
            yes.type = 'button';
            yes.textContent = 'Yes';
            yes.className = 'btn btn-danger btn-xs confirm-yes';
            yes.addEventListener('click', function () { form.submit(); });

            var no = document.createElement('button');
            no.type = 'button';
            no.textContent = 'No';
            no.className = 'btn btn-secondary btn-xs confirm-no';
            no.addEventListener('click', function () {
                btn.style.display = '';
                yes.remove();
                no.remove();
                label.remove();
            });

            form.appendChild(label);
            form.appendChild(yes);
            form.appendChild(no);
        });
    });

    var incomeToggle = document.getElementById('income-toggle');
    if (incomeToggle) {
        incomeToggle.addEventListener('change', function () {
            this.closest('form').submit();
        });
    }

    document.querySelectorAll('.flash-message').forEach(function (el) {
        setTimeout(function () {
            el.style.transition = 'opacity 0.5s';
            el.style.opacity = '0';
            setTimeout(function () { el.remove(); }, 500);
        }, 4000);
    });

});