document.addEventListener('DOMContentLoaded', function() {
    // Chart instances
    let statusChart, sourceChart, timeChart;

    // A modern color palette
    const colorPalette = [
        '#0d6efd', '#198754', '#ffc107', '#dc3545', '#0dcaf0', '#6c757d',
        '#d63384', '#fd7e14', '#20c997', '#6610f2'
    ];
    
    /**
     * Creates a new Chart.js instance or updates an existing one.
     * @param {Chart} chartInstance - The existing chart instance, if any.
     * @param {CanvasRenderingContext2D} context - The canvas context to draw on.
     * @param {string} type - The type of chart (e.g., 'doughnut', 'pie', 'line').
     * @param {object} data - The chart data configuration.
     * @param {object} options - The chart options configuration.
     * @returns {Chart} The new or updated chart instance.
     */
    function createOrUpdateChart(chartInstance, context, type, data, options) {
        if (chartInstance) {
            chartInstance.destroy();
        }
        return new Chart(context, { type, data, options });
    }
    
    /**
     * Fetches all necessary data from the backend and updates the UI.
     */
    async function fetchDashboardData() {
        try {
            // Fetch stats and quote in parallel for faster loading
            const [statsResponse, quoteResponse] = await Promise.all([
                fetch('/api/dashboard_stats'),
                fetch('/api/quote')
            ]);

            if (!statsResponse.ok || !quoteResponse.ok) {
                throw new Error('Network response was not ok.');
            }

            const stats = await statsResponse.json();
            const quoteData = await quoteResponse.json();

            // === Update UI ===

            // Motivational Quote
            document.getElementById('motivationalQuote').innerHTML = `"${quoteData.quote}" <br><em>- ${quoteData.author}</em>`;

            // KPIs
            document.getElementById('jobsScraped24h').textContent = stats.jobs_scraped_last_24_hours || 0;
            const pendingApps = (stats.application_status_breakdown?.inbox || 0) + (stats.application_status_breakdown?.want_to_apply || 0);
            document.getElementById('jobsToBeApplied').textContent = pendingApps;
            document.getElementById('totalApplications').textContent = stats.total_applications || 0;
            
            // Calculate and update the combined total for Resumes/CVs
            const totalDocuments = (stats.resumes_created_total || 0) + (stats.cover_letters_created_total || 0);
            document.getElementById('totalDocumentsGenerated').textContent = totalDocuments;


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
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed !== null) {
                                    label += context.parsed;
                                }
                                return label;
                            }
                        }
                    }
                }
            };

            const noDataAvailable = (dataObject) => !dataObject || Object.keys(dataObject).length === 0;

            // Status Breakdown Chart (Doughnut)
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

            // Applications by Source Chart (Pie)
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

            // Applications Over Time Chart (Line)
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
                plugins: { legend: { display: false } },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1
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

    // Initial data load on page view
    fetchDashboardData();
    
    // Optional: Refresh data periodically if desired
    // setInterval(fetchDashboardData, 60000); // e.g., refresh every 60 seconds
});
