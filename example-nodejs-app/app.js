const express = require('express');
const cors = require('cors');
const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static('public'));

// Routes
app.get('/', (req, res) => {
    res.send(`
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Simple Blog App</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                .header { text-align: center; color: #333; margin-bottom: 30px; }
                .info { background: #e8f4fd; padding: 15px; border-radius: 5px; margin: 15px 0; }
                .success { background: #d4edda; color: #155724; padding: 15px; border-radius: 5px; margin: 15px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚀 Simple Blog App</h1>
                    <p>Node.js Application deployed via GitHub Actions</p>
                </div>
                
                <div class="success">
                    ✅ Application is running successfully!
                </div>
                
                <div class="info">
                    <h3>System Information</h3>
                    <p><strong>Node.js Version:</strong> ${process.version}</p>
                    <p><strong>Environment:</strong> ${process.env.NODE_ENV || 'development'}</p>
                    <p><strong>Timestamp:</strong> ${new Date().toISOString()}</p>
                </div>
                
                <div class="info">
                    <h3>API Endpoints</h3>
                    <p><a href="/api/health">Health Check</a></p>
                    <p><a href="/api/info">System Info</a></p>
                </div>
            </div>
        </body>
        </html>
    `);
});

app.get('/api/health', (req, res) => {
    res.json({
        status: 'healthy',
        timestamp: new Date().toISOString(),
        uptime: process.uptime()
    });
});

app.get('/api/info', (req, res) => {
    res.json({
        status: 'success',
        message: 'Simple Blog App Node.js Application',
        version: '1.0.0',
        node_version: process.version,
        environment: process.env.NODE_ENV || 'development',
        timestamp: new Date().toISOString()
    });
});

app.listen(PORT, () => {
    console.log(`🚀 Simple Blog App server running on port ${PORT}`);
    console.log(`📍 Environment: ${process.env.NODE_ENV || 'development'}`);
});
