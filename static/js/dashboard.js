document.addEventListener('DOMContentLoaded', function() {
    // Goals are now passed from the template
    const dailyGoalTargetElement = document.getElementById('dailyGoalTarget');
    const weeklyGoalTargetElement = document.getElementById('weeklyGoalTarget');

    const dailyGoal = dailyGoalTargetElement ? parseInt(dailyGoalTargetElement.textContent) : 10;
    const weeklyGoal = weeklyGoalTargetElement ? parseInt(weeklyGoalTargetElement.textContent) : 50;

    let applicationsOverTimeChartInstance = null;
    let applicationsBySourceChartInstance = null;
    let applicationStatusChartInstance = null;

    const chartColors = [
        'rgba(255, 99, 132, 0.7)',
        'rgba(54, 162, 235, 0.7)',
        'rgba(255, 206, 86, 0.7)',
        'rgba(75, 192, 192, 0.7)',
        'rgba(153, 102, 255, 0.7)',
        'rgba(255, 159, 64, 0.7)',
        'rgba(199, 199, 199, 0.7)', // Grey for 'inbox' or 'archived'
        'rgba(83, 102, 83, 0.7)'    // Another color if more statuses
    ];

    const chartBorderColors = [
        'rgba(255, 99, 132, 1)',
        'rgba(54, 162, 235, 1)',
        'rgba(255, 206, 86, 1)',
        'rgba(75, 192, 192, 1)',
        'rgba(153, 102, 255, 1)',
        'rgba(255, 159, 64, 1)',
        'rgba(199, 199, 199, 1)',
        'rgba(83, 102, 83, 1)'
    ];


    function fetchDashboardData() {
        fetch('/api/dashboard_stats')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data) {
                    updateKPIs(data);
                    updateCharts(data);
                    updateDailyGoal(data.applications_today, dailyGoal);
                    updateWeeklyGoal(data.applications_this_week, weeklyGoal);
                } else {
                    console.error('No data received from /api/dashboard_stats');
                    setDefaultKPIs();
                    setDefaultCharts();
                    updateDailyGoal(0, dailyGoal);
                    updateWeeklyGoal(0, weeklyGoal);
                }
            })
            .catch(error => {
                console.error('Error fetching dashboard stats:', error);
                setDefaultKPIs();
                setDefaultCharts();
                updateDailyGoal(0, dailyGoal);
                updateWeeklyGoal(0, weeklyGoal);
                document.getElementById('motivationalQuote').textContent = 'Error loading dashboard data. Please try again later.';
            });
    }

    function fetchMotivationalQuote() {
        fetch('/api/quote')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                const quoteElement = document.getElementById('motivationalQuote');
                if (data.quote && data.author) {
                    quoteElement.innerHTML = `"${data.quote}" - <em>${data.author}</em>`;
                } else {
                    quoteElement.textContent = 'Keep pushing, you are doing great!'; // Fallback
                }
            })
            .catch(error => {
                console.error('Error fetching motivational quote:', error);
                document.getElementById('motivationalQuote').textContent = 'Stay motivated! (Error fetching quote)'; // Fallback
            });
    }

    function setDefaultKPIs() {
        document.getElementById('jobsScraped24h').textContent = '0';
        document.getElementById('applicationsToday').textContent = '0';
        document.getElementById('applicationsThisWeek').textContent = '0';
        document.getElementById('totalApplications').textContent = '0';
        document.getElementById('resumesCreatedToday').textContent = '0';
        document.getElementById('totalResumesCreated').textContent = '0';
        document.getElementById('coverLettersCreatedToday').textContent = '0';
        document.getElementById('totalCoverLettersCreated').textContent = '0';
        document.getElementById('jobsToBeApplied').textContent = '0';
    }

    function updateKPIs(data) {
        document.getElementById('jobsScraped24h').textContent = data.jobs_scraped_last_24_hours !== undefined ? data.jobs_scraped_last_24_hours : 0;
        document.getElementById('applicationsToday').textContent = data.applications_today !== undefined ? data.applications_today : 0;
        document.getElementById('applicationsThisWeek').textContent = data.applications_this_week !== undefined ? data.applications_this_week : 0;
        document.getElementById('totalApplications').textContent = data.total_applications !== undefined ? data.total_applications : 0;

        // Calculate Jobs to be Applied
        let jobsToBeAppliedCount = 0;
        if (data.application_status_breakdown) {
            jobsToBeAppliedCount += data.application_status_breakdown['inbox'] || 0;
            jobsToBeAppliedCount += data.application_status_breakdown['want_to_apply'] || 0;
        }
        document.getElementById('jobsToBeApplied').textContent = jobsToBeAppliedCount;
        document.getElementById('resumesCreatedToday').textContent = data.resumes_created_today !== undefined ? data.resumes_created_today : 0;
        document.getElementById('totalResumesCreated').textContent = data.resumes_created_total !== undefined ? data.resumes_created_total : 0;
        document.getElementById('coverLettersCreatedToday').textContent = data.cover_letters_created_today !== undefined ? data.cover_letters_created_today : 0;
        document.getElementById('totalCoverLettersCreated').textContent = data.cover_letters_created_total !== undefined ? data.cover_letters_created_total : 0;
        // Update weekly goal counter display
        document.getElementById('appliedThisWeekCount').textContent = data.applications_this_week !== undefined ? data.applications_this_week : 0;
    }

    function updateGoalProgress(currentValue, goalValue, countElementId, progressBarId) {
        const countElement = document.getElementById(countElementId);
        const progressBarElement = document.getElementById(progressBarId);

        currentValue = currentValue || 0;
        if (countElement) {
            countElement.textContent = currentValue;
        }

        if (progressBarElement && goalValue > 0) {
            const percentage = Math.min((currentValue / goalValue) * 100, 100);
            progressBarElement.style.width = percentage + '%';
            progressBarElement.setAttribute('aria-valuenow', currentValue);
            progressBarElement.textContent = `${Math.round(percentage)}%`;

            progressBarElement.classList.remove('bg-success', 'bg-warning', 'bg-info', 'bg-danger');
            if (percentage >= 100) {
                progressBarElement.classList.add('bg-success');
            } else if (percentage >= 75) {
                progressBarElement.classList.add('bg-info');
            } else if (percentage >= 50) {
                progressBarElement.classList.add('bg-warning');
            } else {
                progressBarElement.classList.add('bg-danger');
            }
        } else if (progressBarElement) { // Goal is 0 or not set, show 0%
            progressBarElement.style.width = '0%';
            progressBarElement.setAttribute('aria-valuenow', 0);
            progressBarElement.textContent = `0%`;
            progressBarElement.classList.add('bg-secondary');
        }
    }

    function updateDailyGoal(appliedToday, goal) {
        updateGoalProgress(appliedToday, goal, 'appliedTodayCount', 'dailyGoalProgress');
    }

    function updateWeeklyGoal(appliedThisWeek, goal) {
        updateGoalProgress(appliedThisWeek, goal, 'appliedThisWeekCount', 'weeklyGoalProgress');
    }

    const defaultChartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true,
                position: 'top',
            },
            tooltip: {
                enabled: true
            }
        }
    };

    const noDataConfig = (label) => ({
        labels: ['No Data'],
        datasets: [{
            label: label,
            data: [1], // Chart.js needs at least one data point to render
            backgroundColor: ['rgba(200, 200, 200, 0.2)'],
            borderColor: ['rgba(200, 200, 200, 1)'],
            borderWidth: 1
        }]
    });

    function updateCharts(data) {
        // Applications Over Time Chart
        const ctxTime = document.getElementById('applicationsOverTimeChart').getContext('2d');
        const timeLabels = data.applications_last_7_days && data.applications_last_7_days.length > 0
            ? data.applications_last_7_days.map(item => item.date.substring(5)) // MM-DD format
            : ['No Data'];
        const timeData = data.applications_last_7_days && data.applications_last_7_days.length > 0
            ? data.applications_last_7_days.map(item => item.count)
            : [0]; // Provide 0 for "No Data" to avoid chart errors

        if (applicationsOverTimeChartInstance) {
            applicationsOverTimeChartInstance.destroy();
        }
        applicationsOverTimeChartInstance = new Chart(ctxTime, {
            type: 'line',
            data: {
                labels: timeLabels,
                datasets: [{
                    label: 'Applications per Day',
                    data: timeData,
                    borderColor: 'rgb(75, 192, 192)',
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    tension: 0.1,
                    fill: true
                }]
            },
            options: {
                ...defaultChartOptions,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1,
                            precision: 0 // Ensure y-axis shows whole numbers for counts
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: timeLabels[0] !== 'No Data' // Hide legend if no data
                    }
                }
            }
        });

        // Applications by Source Chart
        const ctxSource = document.getElementById('applicationsBySourceChart').getContext('2d');
        const sourceLabels = data.applications_by_source && Object.keys(data.applications_by_source).length > 0 ? Object.keys(data.applications_by_source) : ['No Data'];
        const sourceData = data.applications_by_source && Object.keys(data.applications_by_source).length > 0 ? Object.values(data.applications_by_source) : [1];

        if (applicationsBySourceChartInstance) {
            applicationsBySourceChartInstance.destroy();
        }
        applicationsBySourceChartInstance = new Chart(ctxSource, {
            type: 'pie',
            data: {
                labels: sourceLabels,
                datasets: [{
                    label: 'Applications by Source',
                    data: sourceData,
                    backgroundColor: chartColors.slice(0, sourceLabels.length),
                    borderColor: chartBorderColors.slice(0, sourceLabels.length),
                    borderWidth: 1
                }]
            },
            options: {
                ...defaultChartOptions,
                plugins: {
                    legend: {
                        display: sourceLabels[0] !== 'No Data' // Hide legend if no data
                    }
                }
            }
        });

        // Application Status Breakdown Chart
        const ctxStatus = document.getElementById('applicationStatusChart').getContext('2d');
        const statusLabels = data.application_status_breakdown && Object.keys(data.application_status_breakdown).length > 0 ? Object.keys(data.application_status_breakdown) : ['No Data'];
        const statusData = data.application_status_breakdown && Object.keys(data.application_status_breakdown).length > 0 ? Object.values(data.application_status_breakdown) : [1];

        if (applicationStatusChartInstance) {
            applicationStatusChartInstance.destroy();
        }
        applicationStatusChartInstance = new Chart(ctxStatus, {
            type: 'doughnut',
            data: {
                labels: statusLabels,
                datasets: [{
                    label: 'Application Status',
                    data: statusData,
                    backgroundColor: chartColors.slice(0, statusLabels.length),
                    borderColor: chartBorderColors.slice(0, statusLabels.length),
                    borderWidth: 1
                }]
            },
            options: {
                ...defaultChartOptions,
                plugins: {
                    legend: {
                        display: statusLabels[0] !== 'No Data' // Hide legend if no data
                    }
                }
            }
        });
    }

    function setDefaultCharts() {
        const ctxTime = document.getElementById('applicationsOverTimeChart').getContext('2d');
        if (applicationsOverTimeChartInstance) applicationsOverTimeChartInstance.destroy();
        applicationsOverTimeChartInstance = new Chart(ctxTime, { type: 'line', data: noDataConfig('Applications per Day'), options: {...defaultChartOptions, scales: { y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 }}}, plugins: { legend: { display: false }}} });

        const ctxSource = document.getElementById('applicationsBySourceChart').getContext('2d');
        if (applicationsBySourceChartInstance) applicationsBySourceChartInstance.destroy();
        applicationsBySourceChartInstance = new Chart(ctxSource, { type: 'pie', data: noDataConfig('Applications by Source'), options: {...defaultChartOptions, plugins: { legend: { display: false }}} });

        const ctxStatus = document.getElementById('applicationStatusChart').getContext('2d');
        if (applicationStatusChartInstance) applicationStatusChartInstance.destroy();
        applicationStatusChartInstance = new Chart(ctxStatus, { type: 'doughnut', data: noDataConfig('Application Status'), options: {...defaultChartOptions, plugins: { legend: { display: false }}} });
    }


    // Initial data load
    // Check if a refresh was requested from another page
    if (sessionStorage.getItem('dashboardNeedsRefresh') === 'true') { // Check for 'true' string
        console.log('Dashboard refresh requested from another page. Fetching fresh data.');
        fetchDashboardData();
        sessionStorage.removeItem('dashboardNeedsRefresh'); // Clear the flag after use
    } else {
        fetchDashboardData(); // Always fetch on load for the first visit or if no flag
    }
    fetchMotivationalQuote();

    // Optional: Refresh data periodically
    // setInterval(fetchDashboardData, 60000); // Refresh every 60 seconds
    // setInterval(fetchMotivationalQuote, 300000); // Refresh quote every 5 minutes
});