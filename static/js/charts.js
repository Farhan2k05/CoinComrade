let mainChart = null;
let chartData = [];
let allCategories = [];

document.addEventListener('DOMContentLoaded', function () {
    const dataEl = document.getElementById('chart-data');
    if (dataEl) {
        chartData = [...JSON.parse(dataEl.textContent)].reverse();

        const categoriesSet = new Set();
        chartData.forEach(month => {
            if (month.categories) {
                month.categories.forEach(cat => categoriesSet.add(cat.name));
            }
        });
        allCategories = Array.from(categoriesSet).sort();

        const ctxMain = document.getElementById('mainChart');
        if (ctxMain) drawOverviewChart(ctxMain);

        const categorySelect = document.getElementById('category-selector');
        if (categorySelect) {
            allCategories.forEach(function(cat) {
                const option = document.createElement('option');
                option.value = cat;
                option.textContent = cat;
                categorySelect.appendChild(option);
            });
        }
    }

    document.querySelectorAll('.budget-bar-fill').forEach(function(el) {
        el.style.width = el.dataset.pct + '%';
        el.style.background = el.dataset.color;
    });

    document.querySelectorAll('.goal-progress-fill').forEach(function(el) {
        el.style.width = el.dataset.pct + '%';
    });

    var list = document.getElementById('peer-insights-list');
    if (list) {
        var activeCats = list.dataset.matchCats ? list.dataset.matchCats.split(',').filter(Boolean) : [];
        var incomeOn = list.dataset.matchIncome === '1';

        function setActive(el, on) {
            if (on) {
                el.classList.add('peer-chip-active');
            } else {
                el.classList.remove('peer-chip-active');
            }
        }

        function fetchInsights() {
            var params = new URLSearchParams();
            activeCats.forEach(function(c) { params.append('match_cat', c); });
            params.set('match_income', incomeOn ? '1' : '0');

            list.innerHTML = '<li class="text-gray font-italic">Updating...</li>';

            fetch('/peer_insights?' + params.toString())
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data.insights || data.insights.length === 0) {
                        list.innerHTML = '<li class="text-gray font-italic">No peer data available for the selected filters.</li>';
                        return;
                    }
                    list.innerHTML = data.insights.map(function(i) {
                        return '<li>' + i + '</li>';
                    }).join('');
                })
                .catch(function() {
                    list.innerHTML = '<li class="text-gray font-italic">Could not load peer data.</li>';
                });
        }

        document.querySelectorAll('.peer-chip[data-cat]').forEach(function(chip) {
            var cat = chip.dataset.cat;
            chip.addEventListener('click', function(e) {
                e.stopPropagation();
                var idx = activeCats.indexOf(cat);
                if (idx === -1) activeCats.push(cat);
                else activeCats.splice(idx, 1);
                setActive(chip, activeCats.indexOf(cat) !== -1);
                fetchInsights();
            });
        });

        var incomeToggle = document.getElementById('income-toggle');
        if (incomeToggle) {
            incomeToggle.addEventListener('click', function(e) {
                e.stopPropagation();
                incomeOn = !incomeOn;
                setActive(incomeToggle, incomeOn);
                fetchInsights();
            });
        }
    }
});

function drawOverviewChart(ctx) {
    if (mainChart) mainChart.destroy();

    mainChart = new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: {
            labels: chartData.map(d => d.month_name),
            datasets: [
                {
                    label: 'Income',
                    data: chartData.map(d => d.income),
                    backgroundColor: '#27ae60'
                },
                {
                    label: 'Expenses',
                    data: chartData.map(d => d.expense),
                    backgroundColor: '#e74c3c'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom' }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: v => '£' + v.toLocaleString()
                    }
                }
            }
        }
    });
}

function drawSavingsChart(ctx) {
    if (mainChart) mainChart.destroy();

    const savingsData = chartData.map(d => +(d.income - d.expense).toFixed(2));

    mainChart = new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: {
            labels: chartData.map(d => d.month_name),
            datasets: [{
                label: 'Net Savings',
                data: savingsData,
                borderColor: '#0056b3',
                backgroundColor: 'rgba(0,86,179,0.1)',
                borderWidth: 2,
                fill: true,
                pointBackgroundColor: savingsData.map(v => v >= 0 ? '#27ae60' : '#e74c3c'),
                pointRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom' }
            },
            scales: {
                y: {
                    ticks: {
                        callback: v => '£' + v.toLocaleString()
                    }
                }
            }
        }
    });
}

function drawCategoryChart(ctx, category) {
    if (mainChart) mainChart.destroy();

    const categoryData = chartData.map(month => {
        if (!month.categories) return 0;
        const cat = month.categories.find(c => c.name === category);
        return cat ? +cat.val.toFixed(2) : 0;
    });

    mainChart = new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: {
            labels: chartData.map(d => d.month_name),
            datasets: [{
                label: category + ' Spending',
                data: categoryData,
                borderColor: '#9b59b6',
                backgroundColor: 'rgba(155,89,182,0.1)',
                borderWidth: 2,
                fill: true,
                pointBackgroundColor: '#9b59b6',
                pointRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom' }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: v => '£' + v.toLocaleString()
                    }
                }
            }
        }
    });
}

function updateChart() {
    const selector = document.getElementById('trend-selector');
    const categorySelector = document.getElementById('category-selector-wrap');
    const ctx = document.getElementById('mainChart');
    const val = selector.value;

    if (val === 'overview') {
        categorySelector.style.display = 'none';
        drawOverviewChart(ctx);
    } else if (val === 'savings') {
        categorySelector.style.display = 'none';
        drawSavingsChart(ctx);
    } else if (val === 'category') {
        categorySelector.style.display = 'block';
        const catSelect = document.getElementById('category-selector');
        if (catSelect.value) {
            drawCategoryChart(ctx, catSelect.value);
        } else {
            drawOverviewChart(ctx);
        }
    }
}

function updateCategoryChart() {
    const catSelect = document.getElementById('category-selector');
    const ctx = document.getElementById('mainChart');
    if (catSelect.value) {
        drawCategoryChart(ctx, catSelect.value);
    }
}