document.addEventListener('DOMContentLoaded', function () {

    var usernameInput = document.getElementById('username');
    var usernameFeedback = document.getElementById('username-feedback');
    var passwordInput = document.getElementById('password');
    var strengthBar = document.getElementById('strength-bar');
    var strengthLabel = document.getElementById('strength-label');
    var confirmInput = document.getElementById('confirm_password');
    var matchFeedback = document.getElementById('match-feedback');

    if (usernameInput && usernameFeedback) {
        usernameInput.addEventListener('blur', function () {
            var val = this.value.trim();
            if (val.length < 3) return;
            fetch('/check-username?username=' + encodeURIComponent(val))
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.exists) {
                        usernameFeedback.textContent = 'Username already taken.';
                        usernameFeedback.className = 'field-feedback feedback-error';
                    } else {
                        usernameFeedback.textContent = 'Username is available.';
                        usernameFeedback.className = 'field-feedback feedback-ok';
                    }
                });
        });
    }

    if (passwordInput && strengthBar && strengthLabel) {
        passwordInput.addEventListener('input', function () {
            var pw = this.value;
            var score = 0;
            if (pw.length >= 8)           score++;
            if (pw.length >= 12)          score++;
            if (/[A-Z]/.test(pw))         score++;
            if (/[0-9]/.test(pw))         score++;
            if (/[^A-Za-z0-9]/.test(pw))  score++;

            var levels = [
                { label: '',        color: '',          width: '0%'   },
                { label: 'Weak',    color: '#e53e3e',   width: '25%'  },
                { label: 'Fair',    color: '#ed8936',   width: '50%'  },
                { label: 'Good',    color: '#4299e1',   width: '75%'  },
                { label: 'Strong',  color: '#48bb78',   width: '100%' }
            ];
            var level = pw.length === 0 ? 0 : Math.min(score, 4);
            strengthBar.style.width = levels[level].width;
            strengthBar.style.background = levels[level].color;
            strengthLabel.textContent = levels[level].label;
            strengthLabel.style.color = levels[level].color;
        });
    }

    if (confirmInput && matchFeedback) {
        confirmInput.addEventListener('input', function () {
            if (this.value === '') {
                matchFeedback.textContent = '';
                return;
            }
            if (this.value === passwordInput.value) {
                matchFeedback.textContent = 'Passwords match.';
                matchFeedback.className = 'field-feedback feedback-ok';
            } else {
                matchFeedback.textContent = 'Passwords do not match.';
                matchFeedback.className = 'field-feedback feedback-error';
            }
        });
    }

    document.querySelectorAll('.toggle-pw').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var input = document.getElementById(this.dataset.target);
            if (input.type === 'password') {
                input.type = 'text';
                this.textContent = 'Hide';
            } else {
                input.type = 'password';
                this.textContent = 'Show';
            }
        });
    });

    document.querySelectorAll('.flash-message').forEach(function (el) {
        setTimeout(function () {
            el.style.transition = 'opacity 0.5s';
            el.style.opacity = '0';
            setTimeout(function () { el.remove(); }, 500);
        }, 4000);
    });

});