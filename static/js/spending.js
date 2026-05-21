var trendData = [];
var activeTrendIndex = -1;

document.addEventListener('DOMContentLoaded', function () {
    var el = document.getElementById('trend-data');
    if (el) {
        trendData = JSON.parse(el.textContent);
    }
});

function toggleMonthly() {
    var body = document.getElementById('monthly-breakdown-body');
    var btn  = document.getElementById('monthly-toggle');
    body.classList.toggle('display-none');
    btn.classList.toggle('open');
}

function selectTrend(btn) {
    var index = parseInt(btn.getAttribute('data-index'), 10);
    var panel = document.getElementById('trend-detail-panel');
    var placeholder = '<div class="trend-detail-placeholder">Select a category above to see details and tips.</div>';

    if (activeTrendIndex === index) {
        activeTrendIndex = -1;
        panel.innerHTML = placeholder;
        document.querySelectorAll('.trend-chip').forEach(function (c) { c.classList.remove('trend-chip-active'); });
        return;
    }

    activeTrendIndex = index;
    document.querySelectorAll('.trend-chip').forEach(function (c) { c.classList.remove('trend-chip-active'); });
    btn.classList.add('trend-chip-active');

    var t   = trendData[index];
    var tip = t.tip ? '<div class="trend-tip">' + t.tip + '</div>' : '';
    panel.innerHTML = '<div class="trend-description">' + t.description + '</div>' + tip;
}