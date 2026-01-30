# Settings Component Implementation

I'll create a complete settings component that combines all the requirements from the provided code. This will include sections for webhook configuration, MCP servers management, and VS Code integration with a clean, modern UI.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Settings Component</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            background: linear-gradient(135deg, #1a2a6c, #b21f1f, #1a2a6c);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        
        .container {
            width: 100%;
            max-width: 800px;
        }
        
        .settings-card {
            background: rgba(30, 30, 46, 0.85);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            overflow: hidden;
            margin-bottom: 25px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .settings-header {
            padding: 20px;
            background: rgba(20, 20, 35, 0.9);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .settings-header h1 {
            font-size: 24px;
            margin-bottom: 5px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .settings-header p {
            color: #a0a0c0;
            font-size: 14px;
        }
        
        .settings-content {
            padding: 25px;
        }
        
        .section-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .section-title h2 {
            font-size: 18px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .section-title h2 i {
            color: #4dabf7;
        }
        
        .btn {
            background: linear-gradient(45deg, #4dabf7, #3b5bdb);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(77, 171, 247, 0.3);
        }
        
        .btn:active {
            transform: translateY(0);
        }
        
        .btn-danger {
            background: linear-gradient(45deg, #ff6b6b, #ff0000);
        }
        
        .btn-danger:hover {
            box-shadow: 0 4px 10px rgba(255, 107, 107, 0.3);
        }
        
        .btn-success {
            background: linear-gradient(45deg, #51cf66, #20bd4b);
        }
        
        .btn-success:hover {
            box-shadow: 0 4px 10px rgba(81, 207, 102, 0.3);
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-size: 14px;
            color: #b0b0d0;
        }
        
        .form-control {
            width: 100%;
            padding: 12px 15px;
            background: rgba(20, 20, 35, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            color: white;
            font-size: 14px;
            transition: all 0.3s ease;
        }
        
        .form-control:focus {
            outline: none;
            border-color: #4dabf7;
            box-shadow: 0 0 0 3px rgba(77, 171, 247, 0.2);
        }
        
        .status {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 5px;
            font-size: 14px;
        }
        
        .status-indicator {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #51cf66;
        }
        
        .status-indicator.disconnect {
            background: #ff6b6b;
        }
        
        .server-item {
            background: rgba(20, 20, 35, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.3s ease;
        }
        
        .server-item:hover {
            background: rgba(40, 40, 60, 0.8);
            transform: translateY(-2px);
        }
        
        .server-info {
            flex: 1;
        }
        
        .server-name {
            font-weight: 600;
            margin-bottom: 5px;
            font-size: 16px;
        }
        
        .server-details {
            display: flex;
            gap: 15px;
            font-size: 13px;
            color: #a0a0c0;
        }
        
        .server-details span {
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .server-actions {
            display: flex;
            gap: 10px;
        }
        
        .save-btn {
            background: linear-gradient(45deg, #4dabf7, #3b5bdb);
            color: white;
            border: none;
            padding: 12px 25px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s ease;
            margin-top: 20px;
            width: 100%;
        }
        
        .save-btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 5px 15px rgba(77, 171, 247, 0.4);
        }
        
        .save-btn:disabled {
            background: #3a3a5a;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }
        
        .save-btn:not(:disabled):active {
            transform: translateY(0);
        }
        
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: #a0a0c0;
        }
        
        .empty-state i {
            font-size: 40px;
            margin-bottom: 15px;
            opacity: 0.5;
        }
        
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            opacity: 0;
            visibility: hidden;
            transition: all 0.3s ease;
        }
        
        .modal.active {
            opacity: 1;
            visibility: visible;
        }
        
        .modal-content {
            background: rgba(30, 30, 46, 0.95);
            border-radius: 15px;
            width: 90%;
            max-width: 500px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.1);
            transform: translateY(20px);
            transition: transform 0.3s ease;
        }
        
        .modal.active .modal-content {
            transform: translateY(0);
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .modal-header h3 {
            font-size: 20px;
        }
        
        .close-modal {
            background: none;
            border: none;
            color: #a0a0c0;
            font-size: 24px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .close-modal:hover {
            color: white;
            transform: rotate(90deg);
        }
        
        .modal-actions {
            display: flex;
            gap: 10px;
            margin-top: 25px;
        }
        
        .modal-actions .btn {
            flex: 1;
        }
        
        .notification {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 25px;
            border-radius: 8px;
            background: rgba(30, 30, 46, 0.95);
            border-left: 4px solid #4dabf7;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
            transform: translateX(200%);
            transition: transform 0.4s ease;
            z-index: 1001;
        }
        
        .notification.show {
            transform: translateX(0);
        }
        
        .notification.success {
            border-left-color: #51cf66;
        }
        
        .notification.error {
            border-left-color: #ff6b6b;
        }
        
        .notification i {
            margin-right: 10px;
        }
        
        @media (max-width: 600px) {
            .settings-content {
                padding: 15px;
            }
            
            .server-details {
                flex-direction: column;
                gap: 5px;
            }
            
            .server-actions {
                flex-direction: column;
                gap: 5px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="settings-card">
            <div class="settings-header">
                <h1><i class="fas fa-cog"></i> Settings</h1>
                <p>Manage your application preferences and configurations</p>
            </div>
            
            <div class="settings-content">
                <div class="section-title">
                    <h2><i class="fas fa-link"></i> Webhook Configuration</h2>
                </div>
                
                <div class="form-group">
                    <label for="webhook-url">Webhook URL</label>
                    <input type="url" id="webhook-url" class="form-control" placeholder="https://yourdomain.com/webhook" value="https://api.yourdomain.com/webhook">
                </div>
                
                <div class="form-group">
                    <label for="webhook-secret">Webhook Secret</label>
                    <input type="password" id="webhook-secret" class="form-control" placeholder="Enter secret key" value="your-secret-key-here">
                </div>
                
                <div class="status">
                    <div class="status-indicator"></div>
                    <span>Webhook is active and operational</span>
                </div>
                
                <div class="section-title" style="margin-top: 30px;">
                    <h2><i class="fas fa-server"></i> MCP Servers</h2>
                    <button class="btn" id="add-server-btn"><i class="fas fa-plus"></i> Add Server</button>
                </div>
                
                <div class="server-item">
                    <div class="server-info">
                        <div class="server-name">Primary Server</div>
                        <div class="server-details">
                            <span><i class="fas fa-globe"></i> 192.168.1.10</span>
                            <span><i class="fas fa-database"></i> MongoDB</span>
                            <span><i class="fas fa-clock"></i> Connected</span>
                        </div>
                    </div>
                    <div class="server-actions">
                        <button class="btn btn-success"><i class="fas fa-edit"></i></button>
                        <button class="btn btn-danger"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
                
                <div class="server-item">
                    <div class="server-info">
                        <div class="server-name">Backup Server</div>
                        <div class="server-details">
                            <span><i class="fas fa-globe"></i> 192.168.1.11</span>
                            <span><i class="fas fa-database"></i> PostgreSQL</span>
                            <span><i class="fas fa-clock"></i> Connected</span>
                        </div>
                    </div>
                    <div class="server-actions">
                        <button class="btn btn-success"><i class="fas fa-edit"></i></button>
                        <button class="btn btn-danger"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
                
                <div class="server-item">
                    <div class="server-info">
                        <div class="server-name">Development Server</div>
                        <div class="server-details">
                            <span><i class="fas fa-globe"></i> 192.168.1.12</span>
                            <span><i class="fas fa-database"></i> MySQL</span>
                            <span><i class="fas fa-clock"></i> Disconnected</span>
                        </div>
                    </div>
                    <div class="server-actions">
                        <button class="btn btn-success"><i class="fas fa-edit"></i></button>
                        <button class="btn btn-danger"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
                
                <div class="section-title" style="margin-top: 30px;">
                    <h2><i class="fab fa-github"></i> VS Code Integration</h2>
                </div>
                
                <div class="form-group">
                    <label for="vscode-token">VS Code Personal Access Token</label>
                    <input type="password" id="vscode-token" class="form-control" placeholder="Enter your token">
                </div>
                
                <div class="form-group">
                    <label for="vscode-activity">Activity Status</label>
                    <select id="vscode-activity" class="form-control">
                        <option value="active">Active</option>
                        <option value="idle">Idle</option>
                        <option value="away">Away</option>
                    </select>
                </div>
                
                <div class="status">
                    <div class="status-indicator"></div>
                    <span>VS Code integration is active</span>
                </div>
                
                <button class="save-btn" id="save-settings">
                    <i class="fas fa-save"></i> Save Configuration
                </button>
            </div>
        </div>
    </div>
    
    <!-- Modal for adding server -->
    <div class="modal" id="server-modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>Add New Server</h3>
                <button class="close-modal">&times;</button>
            </div>
            <div class="form-group">
                <label for="server-name">Server Name</label>
                <input type="text" id="server-name" class="form-control" placeholder="Enter server name">
            </div>
            <div class="form-group">
                <label for="server-ip">IP Address</label>
                <input type="text" id="server-ip" class="form-control" placeholder="192.168.1.100">
            </div>
            <div class="form-group">
                <label for="server-db">Database Type</label>
                <select id="server-db" class="form-control">
                    <option value="mongodb">MongoDB</option>
                    <option value="postgresql">PostgreSQL</option>
                    <option value="mysql">MySQL</option>
                </select>
            </div>
            <div class="modal-actions">
                <button class="btn btn-danger" id="cancel-server">Cancel</button>
                <button class="btn btn-success" id="save-server">Add Server</button>
            </div>
        </div>
    </div>
    
    <!-- Notification -->
    <div class="notification" id="notification">
        <i class="fas fa-check-circle"></i> <span id="notification-text">Settings saved successfully!</span>
    </div>

    <script>
        // Modal functionality
        const addServerBtn = document.getElementById('add-server-btn');
        const serverModal = document.getElementById('server-modal');
        const closeModal = document.querySelector('.close-modal');
        const cancelServerBtn = document.getElementById('cancel-server');
        const saveServerBtn = document.getElementById('save-server');
        
        addServerBtn.addEventListener('click', () => {
            serverModal.classList.add('active');
        });
        
        closeModal.addEventListener('click', () => {
            serverModal.classList.remove('active');
        });
        
        cancelServerBtn.addEventListener('click', () => {
            serverModal.classList.remove('active');
        });
        
        saveServerBtn.addEventListener('click', () => {
            const serverName = document.getElementById('server-name').value;
            if (serverName) {
                alert(`Successfully added server: ${serverName}`);
                serverModal.classList.remove('active');
                showNotification('Server added successfully!', 'success');
            }
        });
        
        // Close modal when clicking outside
        window.addEventListener('click', (e) => {
            if (e.target === serverModal) {
                serverModal.classList.remove('active');
            }
        });
        
        // Save settings functionality
        const saveSettingsBtn = document.getElementById('save-settings');
        saveSettingsBtn.addEventListener('click', () => {
            showNotification('Settings saved successfully!', 'success');
        });
        
        // Notification function
        function showNotification(message, type = 'success') {
            const notification = document.getElementById('notification');
            const notificationText = document.getElementById('notification-text');
            
            notificationText.textContent = message;
            notification.className = 'notification show ' + type;
            
            setTimeout(() => {
                notification.classList.remove('show');
            }, 3000);
        }
        
        // Simulate a form submission
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Settings page loaded successfully');
        });
    </script>
</body>
</html>
```
