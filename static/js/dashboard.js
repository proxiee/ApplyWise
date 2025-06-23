document.addEventListener('DOMContentLoaded', function() {
    // Chart instances
    let statusChart, sourceChart, timeChart, goalChart;

    // A modern color palette
    const colorPalette = [
        '#0d6efd', '#198754', '#ffc107', '#dc3545', '#0dcaf0', '#6c757d',
        '#d63384', '#fd7e14', '#20c997', '#6610f2'
    ];
    
    function createOrUpdateChart(chartInstance, context, type, data, options) {
        if (chartInstance) {
            chartInstance.destroy();
        }
        return new Chart(context, { type, data, options });
    }

    function updateWeeklyProgress(applicationsLast7Days) {
        const progressBar = document.getElementById('weekly-goal-progress-bar');
        const progressContainer = document.getElementById('weekly-goal-progress-container');
        
        if (!progressBar || !progressContainer) {
            console.error('Weekly progress bar elements not found.');
            return;
        }

        const weeklyGoal = parseInt(progressContainer.dataset.goal, 10) || 50;
        const applicationsThisWeek = applicationsLast7Days.reduce((total, day) => total + day.count, 0);
        
        const percentage = weeklyGoal > 0 ? (applicationsThisWeek / weeklyGoal) * 100 : 0;
        
        progressBar.style.width = `${Math.min(percentage, 100)}%`;
        progressBar.setAttribute('aria-valuenow', applicationsThisWeek);
        progressBar.setAttribute('aria-valuemax', weeklyGoal);
        progressBar.textContent = `${applicationsThisWeek} / ${weeklyGoal} Applications`;

        progressBar.classList.remove('bg-primary', 'bg-warning', 'bg-success');
        if (percentage >= 100) {
            progressBar.classList.add('bg-success');
        } else if (percentage >= 50) {
            progressBar.classList.add('bg-primary');
        } else {
            progressBar.classList.add('bg-warning');
        }
    }
    
    async function fetchDashboardData() {
        try {
            const [statsResponse, quoteResponse] = await Promise.all([
                fetch('/api/dashboard_stats'),
                fetch('/api/quote')
            ]);

            if (!statsResponse.ok || !quoteResponse.ok) {
                throw new Error('Network response was not ok.');
            }

            const stats = await statsResponse.json();
            const quoteData = await quoteResponse.json();

            // Update UI
            document.getElementById('motivationalQuote').innerHTML = `"${quoteData.quote}" <br><em>- ${quoteData.author}</em>`;
            document.getElementById('jobsScraped24h').textContent = stats.jobs_scraped_last_24_hours || 0;
            const pendingApps = (stats.application_status_breakdown?.inbox || 0) + (stats.application_status_breakdown?.['want to apply'] || 0);
            document.getElementById('jobsToBeApplied').textContent = pendingApps;
            document.getElementById('totalApplications').textContent = stats.total_applications || 0;
            const totalDocuments = (stats.resumes_created_total || 0) + (stats.cover_letters_created_total || 0);
            document.getElementById('totalDocumentsGenerated').textContent = totalDocuments;
            updateWeeklyProgress(stats.applications_last_7_days || []);


            // --- Charts ---
            const baseChartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.label || '';
                                if (label) { label += ': '; }
                                if (context.parsed !== null) { label += context.parsed; }
                                return label;
                            }
                        }
                    }
                }
            };

            const noDataAvailable = (dataObject) => !dataObject || Object.keys(dataObject).length === 0;

            const statusData = stats.application_status_breakdown;
            const statusCtx = document.getElementById('applicationStatusChart').getContext('2d');
            statusChart = createOrUpdateChart(statusChart, statusCtx, 'doughnut', {
                labels: noDataAvailable(statusData) ? ['No Data'] : Object.keys(statusData),
                datasets: [{ 
                    data: noDataAvailable(statusData) ? [1] : Object.values(statusData), 
                    backgroundColor: colorPalette,
                    borderColor: '#fff',
                    borderWidth: 2
                }]
            }, { ...baseChartOptions });

            const sourceData = stats.applications_by_source;
            const sourceCtx = document.getElementById('applicationsBySourceChart').getContext('2d');
            sourceChart = createOrUpdateChart(sourceChart, sourceCtx, 'pie', {
                labels: noDataAvailable(sourceData) ? ['No Data'] : Object.keys(sourceData),
                datasets: [{
                    data: noDataAvailable(sourceData) ? [1] : Object.values(sourceData),
                    backgroundColor: colorPalette.slice().reverse(),
                    borderColor: '#fff',
                    borderWidth: 2
                }]
            }, { ...baseChartOptions });

            const timeData = stats.applications_last_7_days || [];
            const timeCtx = document.getElementById('applicationsOverTimeChart').getContext('2d');
            const timeLabels = timeData.map(d => new Date(d.date + 'T00:00:00').toLocaleDateString(undefined, { weekday: 'short', month: 'numeric', day: 'numeric'}));
            timeChart = createOrUpdateChart(timeChart, timeCtx, 'line', {
                labels: timeLabels,
                datasets: [{ 
                    label: 'Applications', 
                    data: timeData.map(d => d.count), 
                    borderColor: '#198754', 
                    backgroundColor: 'rgba(25, 135, 84, 0.1)',
                    tension: 0.2, 
                    fill: true,
                    pointBackgroundColor: '#198754',
                    pointRadius: 4
                }]
            }, { 
                ...baseChartOptions, 
                plugins: { ...baseChartOptions.plugins, legend: { display: false } },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1,
                            precision: 0
                        }
                    }
                }
            });

        } catch (error) {
            console.error('Failed to fetch dashboard data:', error);
            const quoteElement = document.getElementById('motivationalQuote');
            quoteElement.textContent = 'Could not load dashboard data. Please try again later.';
            quoteElement.classList.replace('alert-info', 'alert-danger');
        }
    }

    // Initial data load
    fetchDashboardData();
    
    // === NEW: Event listener for the reset button ===
    const resetButton = document.getElementById('resetWeeklyProgressBtn');
    if (resetButton) {
        resetButton.addEventListener('click', async function() {
            // Show a confirmation dialog before proceeding
            const isConfirmed = confirm('Are you sure you want to reset your weekly application count? This action cannot be undone.');

            if (isConfirmed) {
                try {
                    this.disabled = true; // Disable button to prevent multiple clicks
                    this.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Resetting...';

                    const response = await fetch('/api/reset_weekly_progress', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    });

                    if (!response.ok) {
                        throw new Error('Failed to reset progress.');
                    }

                    // Refresh the entire dashboard to show the updated progress
                    await fetchDashboardData();

                } catch (error) {
                    console.error('Error resetting progress:', error);
                    alert('An error occurred. Could not reset progress.');
                } finally {
                    // Re-enable the button
                    this.disabled = false;
                    this.innerHTML = '<i class="fas fa-sync-alt"></i> Reset';
                }
            }
        });
    }
});