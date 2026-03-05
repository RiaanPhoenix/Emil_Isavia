/**
 * Emil Isavia - Premium Valet Parking System
 * Main JavaScript functionality
 */

// Global state management
window.EmilIsavia = {
    // Application state
    state: {
        currentBookings: null,
        currentOptimization: null,
        currentSimulation: null,
        systemStatus: null
    },
    
    // Configuration
    config: {
        apiTimeout: 30000,
        autoRefreshInterval: 300000, // 5 minutes
        chartColors: {
            primary: '#0d6efd',
            success: '#198754',
            warning: '#ffc107',
            danger: '#dc3545',
            info: '#0dcaf0'
        }
    },
    
    // Utility functions
    utils: {
        formatDateTime: function(isoString) {
            if (!isoString) return 'N/A';
            try {
                const date = new Date(isoString);
                return date.toLocaleDateString() + ' ' + 
                       date.toLocaleTimeString('en-GB', {
                           hour: '2-digit', 
                           minute: '2-digit'
                       });
            } catch (e) {
                return 'Invalid Date';
            }
        },
        
        formatDuration: function(startIso, endIso) {
            if (!startIso || !endIso) return 'N/A';
            try {
                const start = new Date(startIso);
                const end = new Date(endIso);
                const hours = Math.round((end - start) / (1000 * 60 * 60));
                
                if (hours < 24) {
                    return `${hours}h`;
                }
                const days = Math.floor(hours / 24);
                const remainingHours = hours % 24;
                return `${days}d ${remainingHours}h`;
            } catch (e) {
                return 'Invalid Duration';
            }
        },
        
        formatNumber: function(number, decimals = 0) {
            if (number === null || number === undefined || isNaN(number)) {
                return 'N/A';
            }
            return new Intl.NumberFormat('en-US', {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals
            }).format(number);
        },
        
        showAlert: function(message, type = 'info', duration = 5000) {
            const alertContainer = document.getElementById('alertContainer') || 
                                 document.querySelector('main');
            
            const alertDiv = document.createElement('div');
            alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
            alertDiv.style.position = 'relative';
            alertDiv.style.zIndex = '1050';
            alertDiv.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            
            if (alertContainer) {
                alertContainer.insertBefore(alertDiv, alertContainer.firstChild);
                
                // Auto-remove after specified duration
                if (duration > 0) {
                    setTimeout(() => {
                        if (alertDiv.parentNode) {
                            alertDiv.classList.remove('show');
                            setTimeout(() => alertDiv.remove(), 150);
                        }
                    }, duration);
                }
            }
        },
        
        showSuccess: function(message, duration = 3000) {
            this.showAlert(message, 'success', duration);
        },
        
        showError: function(message, duration = 7000) {
            this.showAlert(message, 'danger', duration);
        },
        
        showWarning: function(message, duration = 5000) {
            this.showAlert(message, 'warning', duration);
        },
        
        showInfo: function(message, duration = 5000) {
            this.showAlert(message, 'info', duration);
        }
    },
    
    // API interaction functions
    api: {
        baseUrl: '',
        
        async request(endpoint, options = {}) {
            const defaultOptions = {
                headers: {
                    'Content-Type': 'application/json',
                },
                timeout: window.EmilIsavia.config.apiTimeout
            };
            
            const mergedOptions = { ...defaultOptions, ...options };
            
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), mergedOptions.timeout);
                
                const response = await fetch(endpoint, {
                    ...mergedOptions,
                    signal: controller.signal
                });
                
                clearTimeout(timeoutId);
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                return await response.json();
            } catch (error) {
                console.error('API request failed:', error);
                
                if (error.name === 'AbortError') {
                    throw new Error('Request timed out');
                }
                throw error;
            }
        },
        
        async getSystemStatus() {
            return await this.request('/api/status');
        },
        
        async getBookings(date, numCustomers) {
            const params = new URLSearchParams({
                date: date,
                customers: numCustomers
            });
            return await this.request(`/api/bookings?${params}`);
        },
        
        async runOptimization(data) {
            return await this.request('/api/optimize', {
                method: 'POST',
                body: JSON.stringify(data)
            });
        },
        
        async runSimulation(data) {
            return await this.request('/api/simulate', {
                method: 'POST',
                body: JSON.stringify(data)
            });
        }
    },
    
    // UI helper functions
    ui: {
        setButtonLoading(button, loading = true, loadingText = 'Loading...') {
            if (!button) return;
            
            if (loading) {
                button.dataset.originalText = button.innerHTML;
                button.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${loadingText}`;
                button.disabled = true;
            } else {
                button.innerHTML = button.dataset.originalText || button.innerHTML;
                button.disabled = false;
            }
        },
        
        updateStatusIndicator(elementId, status, tooltip = '') {
            const element = document.getElementById(elementId);
            if (!element) return;
            
            let icon = '';
            switch (status) {
                case 'connected':
                case 'gurobi_available':
                case 'simpy_available':
                case 'ready':
                    icon = '<i class="fas fa-check-circle text-success"></i>';
                    break;
                case 'mock_data':
                case 'heuristic_only':
                    icon = '<i class="fas fa-exclamation-circle text-warning"></i>';
                    break;
                case 'error':
                default:
                    icon = '<i class="fas fa-times-circle text-danger"></i>';
            }
            
            element.innerHTML = icon;
            if (tooltip) {
                element.title = tooltip;
            }
        },
        
        populateTable(tableBodyId, data, columns) {
            const tbody = document.getElementById(tableBodyId);
            if (!tbody) return;
            
            tbody.innerHTML = '';
            
            if (!data || data.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="${columns.length}" class="text-center text-muted">
                            No data available
                        </td>
                    </tr>
                `;
                return;
            }
            
            data.forEach(row => {
                const tr = document.createElement('tr');
                columns.forEach(column => {
                    const td = document.createElement('td');
                    const value = typeof column === 'string' ? row[column] : column(row);
                    td.innerHTML = value || '';
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
        },
        
        createChart(canvasId, config) {
            const ctx = document.getElementById(canvasId);
            if (!ctx) return null;
            
            // Destroy existing chart if it exists
            if (window.charts && window.charts[canvasId]) {
                window.charts[canvasId].destroy();
            }
            
            // Initialize charts storage
            if (!window.charts) {
                window.charts = {};
            }
            
            try {
                window.charts[canvasId] = new Chart(ctx, config);
                return window.charts[canvasId];
            } catch (error) {
                console.error('Failed to create chart:', error);
                return null;
            }
        }
    },
    
    // Initialize the application
    init: function() {
        console.log('Initializing Emil Isavia system...');
        
        // Set up global error handling
        window.addEventListener('error', (event) => {
            console.error('Global error:', event.error);
            this.utils.showError('An unexpected error occurred. Please refresh the page.');
        });
        
        // Set up unhandled promise rejection handling
        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled promise rejection:', event.reason);
            this.utils.showError('A network error occurred. Please check your connection.');
        });
        
        // Initialize Bootstrap tooltips
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(tooltipTriggerEl => {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
        
        // Initialize Bootstrap popovers
        const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
        popoverTriggerList.map(popoverTriggerEl => {
            return new bootstrap.Popover(popoverTriggerEl);
        });
        
        // Set up auto-refresh if on dashboard
        if (window.location.pathname === '/' || window.location.pathname === '/dashboard') {
            setInterval(() => {
                if (typeof refreshSystemStatus === 'function') {
                    refreshSystemStatus();
                }
            }, this.config.autoRefreshInterval);
        }
        
        console.log('Emil Isavia system initialized successfully');
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.EmilIsavia.init();
});

// Export utilities for global access (backward compatibility)
window.formatDateTime = window.EmilIsavia.utils.formatDateTime;
window.formatDuration = window.EmilIsavia.utils.formatDuration;
window.formatNumber = window.EmilIsavia.utils.formatNumber;
window.showSuccess = window.EmilIsavia.utils.showSuccess;
window.showError = window.EmilIsavia.utils.showError;
window.showWarning = window.EmilIsavia.utils.showWarning;
window.showInfo = window.EmilIsavia.utils.showInfo;