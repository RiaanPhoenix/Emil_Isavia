/**
 * Emil Isavia - Main JavaScript functionality
 */

// Global variables
let systemStatus = {};
let flightData = [];
let lastUpdate = null;

// API utilities
class APIClient {
    constructor() {
        this.baseURL = '';
    }

    async get(endpoint, params = {}) {
        const url = new URL(endpoint, window.location.origin);
        Object.keys(params).forEach(key => url.searchParams.append(key, params[key]));
        
        try {
            const response = await fetch(url);
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    async post(endpoint, data = {}) {
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            });
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }
}

const api = new APIClient();

// Utility functions
function formatDateTime(dateString) {
    if (!dateString) return 'N/A';
    
    try {
        const date = new Date(dateString);
        return date.toLocaleString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return 'Invalid Date';
    }
}

function formatDuration(minutes) {
    if (!minutes) return 'N/A';
    
    const hours = Math.floor(minutes / 60);
    const mins = Math.round(minutes % 60);
    
    if (hours > 0) {
        return `${hours}h ${mins}m`;
    }
    return `${mins}m`;
}

function formatCurrency(amount, currency = 'USD') {
    if (amount === null || amount === undefined) return 'N/A';
    
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency
    }).format(amount);
}

function formatNumber(number, decimals = 0) {
    if (number === null || number === undefined) return 'N/A';
    
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(number);
}

// Status indicator functions
function createStatusIndicator(status, label) {
    const iconClass = status ? 'fas fa-check text-success' : 'fas fa-times text-danger';
    return `<i class="${iconClass}" title="${label}"></i>`;
}

function updateStatusCard(elementId, status, label) {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = createStatusIndicator(status, label);
    }
}

// Loading states
function setLoading(elementId, isLoading = true) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    if (isLoading) {
        element.classList.add('loading');
        if (element.tagName === 'BUTTON') {
            element.disabled = true;
            element.dataset.originalText = element.innerHTML;
            element.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Loading...';
        }
    } else {
        element.classList.remove('loading');
        if (element.tagName === 'BUTTON') {
            element.disabled = false;
            if (element.dataset.originalText) {
                element.innerHTML = element.dataset.originalText;
            }
        }
    }
}

// Table utilities
function clearTable(tableBodyId) {
    const tbody = document.getElementById(tableBodyId);
    if (tbody) {
        tbody.innerHTML = '';
    }
}

function addTableRow(tableBodyId, rowHTML) {
    const tbody = document.getElementById(tableBodyId);
    if (tbody) {
        tbody.innerHTML += rowHTML;
    }
}

function setTableMessage(tableBodyId, message, colspan = 9, type = 'info') {
    const tbody = document.getElementById(tableBodyId);
    if (tbody) {
        const alertClass = type === 'error' ? 'text-danger' : 
                         type === 'warning' ? 'text-warning' : 
                         'text-muted';
        tbody.innerHTML = `
            <tr>
                <td colspan="${colspan}" class="text-center ${alertClass}">
                    ${message}
                </td>
            </tr>
        `;
    }
}

// Chart utilities
function createChart(canvasId, config) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    
    // Destroy existing chart if it exists
    if (window.charts && window.charts[canvasId]) {
        window.charts[canvasId].destroy();
    }
    
    // Initialize charts object
    if (!window.charts) {
        window.charts = {};
    }
    
    // Create new chart
    window.charts[canvasId] = new Chart(ctx, config);
    return window.charts[canvasId];
}

// Data processing utilities
function processFlightData(rawData) {
    if (!Array.isArray(rawData)) return [];
    
    return rawData.map(flight => ({
        ...flight,
        departure_time_formatted: formatDateTime(flight.departure_time),
        arrival_time_formatted: formatDateTime(flight.arrival_time),
        capacity_formatted: formatNumber(flight.passenger_capacity),
        status_badge: `<span class="badge bg-${getStatusColor(flight.status)}">${flight.status}</span>`
    }));
}

function getStatusColor(status) {
    switch (status.toLowerCase()) {
        case 'scheduled': return 'primary';
        case 'departed': return 'success';
        case 'arrived': return 'info';
        case 'delayed': return 'warning';
        case 'cancelled': return 'danger';
        default: return 'secondary';
    }
}

// Notification system
class NotificationManager {
    constructor() {
        this.container = this.createContainer();
    }
    
    createContainer() {
        let container = document.getElementById('notifications');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notifications';
            container.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 1050;
                max-width: 400px;
            `;
            document.body.appendChild(container);
        }
        return container;
    }
    
    show(message, type = 'info', duration = 5000) {
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} alert-dismissible fade show`;
        notification.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        this.container.appendChild(notification);
        
        // Auto-hide
        if (duration > 0) {
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.classList.remove('show');
                    setTimeout(() => notification.remove(), 150);
                }
            }, duration);
        }
    }
    
    success(message, duration = 3000) {
        this.show(message, 'success', duration);
    }
    
    error(message, duration = 7000) {
        this.show(message, 'danger', duration);
    }
    
    warning(message, duration = 5000) {
        this.show(message, 'warning', duration);
    }
    
    info(message, duration = 5000) {
        this.show(message, 'info', duration);
    }
}

const notifications = new NotificationManager();

// Form validation utilities
function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return false;
    
    const inputs = form.querySelectorAll('input[required], select[required]');
    let isValid = true;
    
    inputs.forEach(input => {
        if (!input.value.trim()) {
            input.classList.add('is-invalid');
            isValid = false;
        } else {
            input.classList.remove('is-invalid');
        }
    });
    
    return isValid;
}

function clearFormValidation(formId) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    form.querySelectorAll('.is-invalid').forEach(input => {
        input.classList.remove('is-invalid');
    });
}

// Local storage utilities
function saveToStorage(key, data) {
    try {
        localStorage.setItem(key, JSON.stringify(data));
    } catch (error) {
        console.warn('Could not save to localStorage:', error);
    }
}

function loadFromStorage(key, defaultValue = null) {
    try {
        const stored = localStorage.getItem(key);
        return stored ? JSON.parse(stored) : defaultValue;
    } catch (error) {
        console.warn('Could not load from localStorage:', error);
        return defaultValue;
    }
}

// URL utilities
function updateURLParams(params) {
    const url = new URL(window.location);
    Object.keys(params).forEach(key => {
        if (params[key] !== null && params[key] !== undefined) {
            url.searchParams.set(key, params[key]);
        } else {
            url.searchParams.delete(key);
        }
    });
    window.history.replaceState({}, '', url);
}

function getURLParam(param, defaultValue = null) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(param) || defaultValue;
}

// Export utilities for global access
window.EmilIsavia = {
    api,
    notifications,
    formatDateTime,
    formatDuration,
    formatCurrency,
    formatNumber,
    createStatusIndicator,
    updateStatusCard,
    setLoading,
    clearTable,
    addTableRow,
    setTableMessage,
    createChart,
    processFlightData,
    validateForm,
    clearFormValidation,
    saveToStorage,
    loadFromStorage,
    updateURLParams,
    getURLParam
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('Emil Isavia application initialized');
    
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Initialize popovers
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
    
    // Set up global error handling
    window.addEventListener('error', function(event) {
        console.error('Global error:', event.error);
        notifications.error('An unexpected error occurred. Please refresh the page.');
    });
    
    // Set up unhandled promise rejection handling
    window.addEventListener('unhandledrejection', function(event) {
        console.error('Unhandled promise rejection:', event.reason);
        notifications.error('A network error occurred. Please check your connection.');
    });
});

// Export for testing
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { EmilIsavia: window.EmilIsavia };
}