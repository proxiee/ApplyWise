```javascript
document.addEventListener('DOMContentLoaded', function() {
    const dailyGoal = 50;
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
                    updateDailyGoal(data.applications_today);
                } else {
                    console.error('No data received from /api/dashboard_stats');
                    setDefaultKPIs();
                    setDefaultCharts();
                    updateDailyGoal(0);
                }
            })
            .catch(error => {
                console.error('Error fetching dashboard stats:', error);
                setDefaultKPIs();
                setDefaultCharts();
                updateDailyGoal(0);
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
    }

    function updateKPIs(data) {
        document.getElementById('jobsScraped24h').textContent = data.jobs_scraped_last_24_hours !== undefined ? data.jobs_scraped_last_24_hours : 0;
        document.getElementById('applicationsToday').textContent = data.applications_today !== undefined ? data.applications_today : 0;
        document.getElementById('applicationsThisWeek').textContent = data.applications_this_week !== undefined ? data.applications_this_week : 0;
        document.getElementById('totalApplications').textContent = data.total_applications !== undefined ? data.total_applications : 0;
        document.getElementById('resumesCreatedToday').textContent = data.resumes_created_today !== undefined ? data.resumes_created_today : 0;
        document.getElementById('totalResumesCreated').textContent = data.resumes_created_total !== undefined ? data.resumes_created_total : 0;
    }

    function updateDailyGoal(appliedToday) {
        const appliedCountElement = document.getElementById('appliedTodayCount');
        const progressBarElement = document.getElementById('dailyGoalProgress');

        appliedToday = appliedToday || 0;
        appliedCountElement.textContent = appliedToday;

        const percentage = Math.min((appliedToday / dailyGoal) * 100, 100);
        progressBarElement.style.width = percentage + '%';
        progressBarElement.setAttribute('aria-valuenow', appliedToday);
        progressBarElement.textContent = `${Math.round(percentage)}%`;

        progressBarElement.classList.remove('bg-success', 'bg-warning', 'bg-info');
        if (percentage >= 100) {
            progressBarElement.classList.add('bg-success');
        } else if (percentage >= 50) {
            progressBarElement.classList.add('bg-warning');
        } else {
            progressBarElement.classList.add('bg-info');
        }
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
    fetchDashboardData();
    fetchMotivationalQuote();

    // Optional: Refresh data periodically
    // setInterval(fetchDashboardData, 60000); // Refresh every 60 seconds
    // setInterval(fetchMotivationalQuote, 300000); // Refresh quote every 5 minutes
});
```

And finally, the updated **`templates/jobs.html`**:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Unified Job Board</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}" />
    <style>
        /* Additional styles for better layout if needed */
        .action-btn { margin-right: 5px; margin-bottom: 5px; }
        .badge { display: inline-block; padding: .25em .4em; font-size: 75%; font-weight: 700; line-height: 1; text-align: center; white-space: nowrap; vertical-align: baseline; border-radius: .25rem; }
        .linkedin { background-color: #007bff; color: white; }
        .indeed { background-color: #28a745; color: white; }
        .table th, .table td { vertical-align: middle; }
        .status-select {
            min-width: 120px; /* Adjust as needed */
        }
        .actions button, .actions select {
            margin-bottom: 5px; /* Add some space between buttons/selects if they wrap */
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header-container">
            <h1>My Job Feed</h1>
            <span id="job-count"></span>
        </div>

        <!-- Stats -->
        <div id="stats-container" class="stats-container">Loading stats...</div>

        <!-- Scrape Controls -->
        <div class="controls-container">
            <fieldset>
                <legend>Scrape Controls</legend>
                <div class="controls-grid">
                    <div class="control-group">
                        <label for="source-select">Source:</label>
                        <select id="source-select" onchange="updateTimeUnitOptions()">
                            <option value="all" selected>All Sources</option>
                            <option value="linkedin">LinkedIn Only</option>
                            <option value="indeed">Indeed Only</option>
                        </select>
                    </div>
                    <div class="control-group">
                        <label for="time-value">Time Period:</label>
                        <input type="number" id="time-value" value="7" min="1" />
                        <select id="time-unit"></select>
                    </div>
                    <div class="control-group">
                        <label>Scrape Mode:</label>
                        <div class="radio-group">
                            <input type="radio" id="mode-add" name="scrape-mode" value="add" checked />
                            <label for="mode-add">Add to Inbox</label>
                            <input type="radio" id="mode-archive" name="scrape-mode" value="archive" />
                            <label for="mode-archive">Archive Inbox & Add</label>
                            <input type="radio" id="mode-delete" name="scrape-mode" value="delete" />
                            <label for="mode-delete">Clear Inbox & Add</label>
                        </div>
                    </div>
                </div>
                <div class="scrape-action-bar">
                    <button id="scrape-button" onclick="startScrape()">Scrape New Jobs</button>
                    <span id="scrape-status">Status: Idle</span>
                </div>
            </fieldset>
        </div>

        <!-- Tabs -->
        <div class="tab-container">
            <button class="tab-link active" onclick="openTab('inbox')">Inbox</button>
            <button class="tab-link" onclick="openTab('want_to_apply')">Want to Apply</button>
            <button class="tab-link" onclick="openTab('applied')">Applied</button>
            <button class="tab-link" onclick="openTab('interviewing')">Interviewing</button>
            <button class="tab-link" onclick="openTab('offer')">Offer</button>
            <button class="tab-link" onclick="openTab('rejected')">Rejected</button>
            <button class="tab-link" onclick="openTab('archived')">Archived</button>
            <button class="tab-link" onclick="openResumeCreatorTab()">Create Resume/CV</button>
            <a href="{{ url_for('dashboard_page') }}" class="tab-link">Dashboard</a>
        </div>

        <!-- Jobs -->
        <div id="jobs-content">
            <table id="jobs-table" class="table table-striped">
                <thead>
                    <tr>
                        <th class="index-col">#</th>
                        <th>Source</th>
                        <th>Date Posted</th>
                        <th>Date Loaded</th>
                        <th>Title & Company</th>
                        <th>Location</th>
                        <th>Applied Date</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="jobs-tbody"></tbody>
            </table>
            <div id="loading-spinner" class="spinner"></div>
        </div>
        <div id="resume-creator-content" style="display: none;">
            <h2>Create Resume and Cover Letter</h2>
            <input type="hidden" id="resume-job-id" value="">
            <div><small>Job to tailor for: <span id="resume-job-title-display">None selected. Paste job description below or select a job from the list and click "Generate Resume/CV".</span></small></div>
            <textarea id="job-description-input" placeholder="Job description will be auto-filled if you use 'Generate Resume/CV' from a job row in Inbox/Want to Apply tabs." style="width: 98%; height: 150px; margin-bottom: 10px;"></textarea>
            <button id="generate-resume-cv-button" class="btn btn-primary">Generate Documents</button>
            <div id="resume-creator-status" style="margin-top: 10px; margin-bottom: 10px;"></div>
            <div id="pdf-preview-area" style="display: none; margin-top: 10px;">
                <div style="display: flex; justify-content: space-between; height: 600px;">
                    <iframe id="resume-preview-iframe" style="width: 49%; height: 100%; border: 1px solid #ccc;"></iframe>
                    <iframe id="cv-preview-iframe" style="width: 49%; height: 100%; border: 1px solid #ccc;"></iframe>
                </div>
            </div>
        </div>
    </div>

<script>
    let currentTab = 'inbox';
    let statusInterval;
    const timeUnitSelect = document.getElementById('time-unit');

    const timeOptions = {
        full: `
            <option value="seconds">Seconds</option>
            <option value="minutes">Minutes</option>
            <option value="hours">Hours</option>
            <option value="days" selected>Days</option>
            <option value="weeks">Weeks</option>
            <option value="months">Months</option>
        `,
        indeed: `
            <option value="days" selected>Days</option>
            <option value="weeks">Weeks</option>
            <option value="months">Months</option>
        `
    };
    function updateTimeUnitOptions() {
        const source = document.getElementById('source-select').value;
        timeUnitSelect.innerHTML = (source === 'indeed') ? timeOptions.indeed : timeOptions.full;
    }

    function fetchStats() {
        fetch('/get_stats') // This is the old endpoint, dashboard uses /api/dashboard_stats
            .then(res => res.json())
            .then(stats => {
                document.getElementById('stats-container').innerHTML = `<strong>Jobs Scraped in Last 24 Hours:</strong> ${stats.jobs_last_24_hours}`;
            })
            .catch(err => {
                document.getElementById('stats-container').textContent = 'Could not load stats.';
                console.error('Error fetching stats:', err);
            });
    }

    function openTab(status) {
        currentTab = status;
        document.getElementById('resume-creator-content').style.display = 'none';
        document.getElementById('jobs-content').style.display = 'block';
        document.getElementById('stats-container').style.display = 'block';
        document.querySelector('.controls-container').style.display = 'block';

        document.querySelectorAll('.tab-link').forEach(link => link.classList.remove('active'));
        // More robust way to find the tab button, especially if text content changes slightly
        const tabButtons = document.querySelectorAll('.tab-link');
        tabButtons.forEach(btn => {
            if (btn.getAttribute('onclick') === `openTab('${status}')`) {
                btn.classList.add('active');
            }
        });
        fetchJobs(status);
    }

    function openResumeCreatorTab(jobId = null, jobTitle = null, jobDescription = null) {
        currentTab = 'resume_creator';
        document.getElementById('jobs-content').style.display = 'none';
        document.getElementById('stats-container').style.display = 'none';
        document.querySelector('.controls-container').style.display = 'none';
        document.getElementById('resume-creator-content').style.display = 'block';

        document.querySelectorAll('.tab-link').forEach(link => link.classList.remove('active'));
        const resumeTabButton = Array.from(document.querySelectorAll('.tab-link')).find(el => el.textContent === 'Create Resume/CV');
        if (resumeTabButton) {
            resumeTabButton.classList.add('active');
        }

        const jobDescInput = document.getElementById('job-description-input');
        const resumeJobIdInput = document.getElementById('resume-job-id');
        const resumeJobTitleDisplay = document.getElementById('resume-job-title-display');

        if (jobId && jobDescription !== null) { // Check jobDescription explicitly for null
            resumeJobIdInput.value = jobId;
            jobDescInput.value = jobDescription;
            resumeJobTitleDisplay.textContent = jobTitle ? `For: ${jobTitle}` : `For Job ID: ${jobId}`;
        } else {
            resumeJobIdInput.value = '';
            // jobDescInput.value = ''; // Keep existing text if user typed something before clicking
            resumeJobTitleDisplay.textContent = 'None selected. Paste job description below or select a job from the list and click "Generate Resume/CV".';
        }

        document.getElementById('resume-creator-status').textContent = '';
        document.getElementById('pdf-preview-area').style.display = 'none';
        document.getElementById('resume-preview-iframe').src = 'about:blank';
        document.getElementById('cv-preview-iframe').src = 'about:blank';
    }

    function fetchJobs(status) {
        const tbody = document.getElementById('jobs-tbody');
        const spinner = document.getElementById('loading-spinner');
        const jobCountSpan = document.getElementById('job-count');

        spinner.style.display = 'block';
        tbody.innerHTML = '';
        jobCountSpan.textContent = '';

        fetch(`/get_jobs?status=${status}`)
            .then(res => res.json())
            .then(jobs => {
                spinner.style.display = 'none';
                jobCountSpan.textContent = `(${jobs.length} jobs)`;
                if (!jobs || jobs.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8">No jobs in this category.</td></tr>';
                    return;
                }

                jobs.forEach((job, index) => {
                    const row = document.createElement('tr');
                    row.id = `job-row-${job.id}`;

                    let actionButtons = '';
                    const jobDescriptionEscaped = job.job_description ? job.job_description.replace(/'/g, "\\'").replace(/\n/g, '\\n').replace(/\r/g, '') : '';
                    const jobTitleEscaped = job.title ? job.title.replace(/'/g, "\\'") : 'N/A';

                    // Common "Generate Resume/CV" button for inbox and want_to_apply
                    if (status === 'inbox' || status === 'want_to_apply') {
                         actionButtons += `<button class="action-btn btn btn-sm btn-outline-secondary" onclick="openResumeCreatorTab(${job.id}, '${jobTitleEscaped}', '${jobDescriptionEscaped}')">Generate Docs</button>`;
                    }

                    // Status specific buttons
                    if (status === 'inbox') {
                        actionButtons += `<button class="action-btn btn btn-sm btn-primary" onclick="updateJobStatus(${job.id}, 'want_to_apply')">Bookmark</button>`;
                        actionButtons += `<button class="action-btn btn btn-sm btn-success" onclick="updateJobStatus(${job.id}, 'applied')">Mark Applied</button>`;
                    } else if (status === 'want_to_apply') {
                        actionButtons += `<button class="action-btn btn btn-sm btn-success" onclick="updateJobStatus(${job.id}, 'applied')">Mark Applied</button>`;
                    } else if (['applied', 'interviewing', 'offer', 'rejected'].includes(status)) {
                         actionButtons += `
                            <select class="form-control form-control-sm d-inline-block status-select" onchange="updateJobStatus(${job.id}, this.value)">
                                <option value="applied" ${job.status === 'applied' ? 'selected' : ''}>Applied</option>
                                <option value="interviewing" ${job.status === 'interviewing' ? 'selected' : ''}>Interviewing</option>
                                <option value="offer" ${job.status === 'offer' ? 'selected' : ''}>Offer</option>
                                <option value="rejected" ${job.status === 'rejected' ? 'selected' : ''}>Rejected</option>
                                <option value="archived" ${job.status === 'archived' ? 'selected' : ''}>Archive</option>
                            </select>
                         `;
                    } else if (status === 'archived') {
                         actionButtons += `<button class="action-btn btn btn-sm btn-warning" onclick="updateJobStatus(${job.id}, 'inbox')">Move to Inbox</button>`;
                    }


                    const sourceBadge = job.source === 'LinkedIn' ? '<span class="badge linkedin">LI</span>' : '<span class="badge indeed">IN</span>';
                    let displayDate = 'N/A';
                    if (job.date) {
                        try {
                            // Attempt to parse various date formats that might come from scrapers
                            let parsedDate;
                            if (job.date.match(/^\d{4}-\d{2}-\d{2}$/)) { // YYYY-MM-DD
                                parsedDate = new Date(job.date + "T00:00:00Z"); // Assume UTC if only date
                            } else if (job.date.match(/^\d{1,2}\/\d{1,2}\/\d{4}$/)) { // MM/DD/YYYY
                                const parts = job.date.split('/');
                                parsedDate = new Date(parts[2], parts[0] - 1, parts[1]);
                            } else {
                                parsedDate = new Date(job.date); // General parsing
                            }
                            if (!isNaN(parsedDate)) {
                                displayDate = parsedDate.toLocaleDateString();
                            }
                        } catch (e) {
                            console.warn("Could not parse date:", job.date);
                        }
                    }
                    let scrapedDate = 'N/A';
                    if (job.date_loaded) {
                        const parsedScrapedDate = new Date(job.date_loaded);
                        if (!isNaN(parsedScrapedDate)) {
                            scrapedDate = parsedScrapedDate.toLocaleString();
                        }
                    }
                    let applicationDateStr = 'N/A';
                    if (job.application_date) {
                        const parsedAppDate = new Date(job.application_date);
                        if (!isNaN(parsedAppDate)) {
                            applicationDateStr = parsedAppDate.toLocaleDateString();
                        }
                    }

                    row.innerHTML = `
                        <td class="index-col">${index + 1}</td>
                        <td>${sourceBadge}</td>
                        <td>${displayDate}</td>
                        <td>${scrapedDate}</td>
                        <td>
                            <a href="${job.job_url || '#'}" target="_blank" title="${job.job_description || ''}">${job.title || 'No Title'}</a>
                            <div class="company-name">${job.company || 'No Company'}</div>
                        </td>
                        <td>${job.location || 'No Location'}</td>
                        <td>${applicationDateStr}</td>
                        <td class="actions">${actionButtons}</td>
                    `;
                    tbody.appendChild(row);
                });
            })
            .catch(err => {
                spinner.style.display = 'none';
                console.error('Error fetching jobs:', err);
                tbody.innerHTML = '<tr><td colspan="8">Error fetching jobs.</td></tr>';
            });
    }

    function updateJobStatus(jobId, newStatus) {
        fetch(`/update_job_status/${jobId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ status: newStatus })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // Always refresh the current tab to reflect changes (e.g., application_date appearing)
                fetchJobs(currentTab);
                // If dashboard.js is loaded by another page (it shouldn't be, but as a safeguard)
                if (typeof fetchDashboardData === 'function' && window.location.pathname.endsWith('/dashboard')) {
                    fetchDashboardData(); // Refresh dashboard stats
                }
            } else {
                alert(`Error updating status: ${data.error || 'Unknown error'}`);
            }
        })
        .catch(err => {
            console.error('Error updating job status:', err);
            alert('An error occurred while updating job status.');
        });
    }

    function startScrape() {
        const managementOption = document.querySelector('input[name="scrape-mode"]:checked').value;
        const source = document.getElementById('source-select').value;
        const timeValue = parseInt(document.getElementById('time-value').value, 10);
        const timeUnit = timeUnitSelect.value;

        let daysToScrape = timeValue;
        let timespanSeconds = timeValue * 86400;

        switch (timeUnit) {
            case 'seconds':
                timespanSeconds = timeValue;
                daysToScrape = Math.ceil(timeValue / 86400);
                break;
            case 'minutes':
                timespanSeconds = timeValue * 60;
                daysToScrape = Math.ceil(timeValue / (24 * 60));
                break;
            case 'hours':
                timespanSeconds = timeValue * 3600;
                daysToScrape = Math.ceil(timeValue / 24);
                break;
            case 'weeks':
                daysToScrape = timeValue * 7;
                timespanSeconds = daysToScrape * 86400;
                break;
            case 'months':
                daysToScrape = timeValue * 30;
                timespanSeconds = daysToScrape * 86400;
                break;
        }


        document.getElementById('scrape-button').disabled = true;
        document.getElementById('scrape-status').textContent = 'Status: Starting...';
        statusInterval = setInterval(checkScrapeStatus, 2000);

        fetch('/scrape', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                source: source,
                time_period_str: `${timeValue} ${timeUnit}`,
                timespan: timespanSeconds,
                days: daysToScrape,
                management_option: managementOption
            })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw new Error(err.error || 'Scraping request failed') });
            }
            return response.json();
        })
        .then(data => {
            // Status will be updated by checkScrapeStatus
            console.log(data.message);
        })
        .catch(err => {
            document.getElementById('scrape-status').textContent = `Error: ${err.message}`;
            document.getElementById('scrape-button').disabled = false;
            clearInterval(statusInterval);
        });
    }

    function checkScrapeStatus() {
        fetch('/scrape_status')
            .then(res => res.json())
            .then(status => {
                document.getElementById('scrape-status').textContent = `Status: ${status.message}`;
                if (!status.is_running) {
                    clearInterval(statusInterval);
                    document.getElementById('scrape-button').disabled = false;
                    if (status.message.includes('complete')) {
                        openTab('inbox');
                        fetchStats();
                         if (typeof fetchDashboardData === 'function' && window.location.pathname.endsWith('/dashboard')) {
                            fetchDashboardData();
                        }
                    }
                }
            })
            .catch(() => {
                clearInterval(statusInterval);
                document.getElementById('scrape-button').disabled = false;
                document.getElementById('scrape-status').textContent = 'Status: Error checking status.';
            });
    }

    document.getElementById('generate-resume-cv-button').addEventListener('click', function() {
        const jobDesc = document.getElementById('job-description-input').value;
        const jobId = document.getElementById('resume-job-id').value;
        const statusElement = document.getElementById('resume-creator-status');
        const generateButton = this;
        const pdfPreviewArea = document.getElementById('pdf-preview-area');
        const resumeIframe = document.getElementById('resume-preview-iframe');
        const cvIframe = document.getElementById('cv-preview-iframe');

        if (!jobDesc.trim()) {
            statusElement.textContent = 'Please paste a job description first.';
            statusElement.className = 'status-error';
            return;
        }

        statusElement.textContent = 'Generating documents... This may take a moment.';
        statusElement.className = 'status-info';
        generateButton.disabled = true;
        pdfPreviewArea.style.display = 'none';
        resumeIframe.src = 'about:blank';
        cvIframe.src = 'about:blank';

        const payload = { job_description: jobDesc };
        if (jobId) {
            payload.job_id = parseInt(jobId, 10);
        }

        fetch('/generate_documents', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(errData => {
                    let errorMessage = errData.error || `Server responded with status: ${response.status}`;
                    if (errData.details) {
                        errorMessage += ` - Details: ${errData.details}`;
                    }
                    throw new Error(errorMessage);
                }).catch(parsingError => {
                    console.error('Error parsing JSON error response:', parsingError);
                    return response.text().then(textData => {
                        throw new Error(textData || `Server responded with status: ${response.status}`);
                    });
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                resumeIframe.src = data.resume_pdf_url;
                cvIframe.src = data.cover_letter_pdf_url;
                pdfPreviewArea.style.display = 'block';
                statusElement.textContent = 'Documents generated successfully!';
                statusElement.className = 'status-success';
                // Refresh dashboard stats if the dashboard page is currently active
                if (typeof fetchDashboardData === 'function' && document.getElementById('dashboard-container')) {
                    fetchDashboardData();
                }
            } else {
                statusElement.textContent = `Error: ${data.error || 'Unknown error'}${data.details ? ' - ' + data.details : ''}`;
                statusElement.className = 'status-error';
                console.error('Error generating documents:', data);
            }
        })
        .catch(error => {
            statusElement.textContent = `Request failed: ${error.message}`;
            statusElement.className = 'status-error';
            console.error('Fetch error:', error);
        })
        .finally(() => {
            generateButton.disabled = false;
        });
    });

    // Initial setup
    updateTimeUnitOptions();
    fetchStats(); // For the old stats display on jobs.html
    if (document.getElementById('jobs-tbody')) { // Only call fetchJobs if on jobs.html
        openTab(currentTab); // Load initial tab for jobs page
    }

});
</script>
</body>
</html>
```

I've made some robustness improvements:
*   **`app.py`**:
    *   Added more robust error handling for `config.json` loading.
    *   Improved database initialization to better handle existing databases and potential missing columns.
    *   Ensured `application_date` is explicitly set to `None` when new jobs are committed if the column exists.
    *   Added checks for `None` results from database queries in `get_stats_old` and `api_dashboard_stats` before trying to access `result[0]`.
    *   Added checks for `job_id` being `None` in `generate_documents` and ensured it's passed as `None` (which SQLite handles as NULL) to the DB.
    *   Made the PDF filename parsing in `generate_documents` more robust with a fallback.
    *   Added checks for `app.logger` before using it, just in case.
    *   Strengthened the `serve_pdf` path validation slightly.
*   **`static/js/dashboard.js`**:
    *   Added more robust error handling for `fetch` calls.
    *   Added default "No Data" states for charts if the API returns empty or problematic data.
    *   Improved color cycling for charts if there are more categories than predefined colors.
*   **`templates/jobs.html`**:
    *   Improved the `openTab` function to more reliably find the active tab button.
    *   Ensured `jobDescription` is explicitly checked for `null` before use in `openResumeCreatorTab`.
    *   Added `btn` and `btn-sm` classes to action buttons for better Bootstrap styling.
    *   Added more robust date parsing for `job.date` as its format might vary.
    *   Ensured `fetchDashboardData()` is only called if the dashboard is the current page to avoid errors when `jobs.html` is loaded.
    *   Improved error message display for document generation.
    *   Adjusted `colspan` for "No jobs" message.

After replacing these files and ensuring `requests` is installed, please restart your Flask server and test the `/dashboard` page again. Let me know how it goes!
