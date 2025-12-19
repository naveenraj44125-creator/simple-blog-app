# Node.js Express Demo Application

A simple Node.js Express application demonstrating deployment to AWS Lightsail using the generic deployment system.

**Status**: Ready for deployment

## Features

- Express.js web server
- Health check endpoint
- Application info API
- PM2 process management
- Nginx reverse proxy

## Local Development

```bash
# Install dependencies
npm install

# Run in development mode
npm run dev

# Run in production mode
npm start
```

## Deployment

This application is automatically deployed to AWS Lightsail when changes are pushed to the main branch.

The deployment is configured in:
- `deployment-nodejs.config.yml` - Deployment configuration
- `.github/workflows/deploy-nodejs.yml` - GitHub Actions workflow

## Endpoints

- `GET /` - Home page
- `GET /api/health` - Health check
- `GET /api/info` - Application information

## Environment Variables

- `PORT` - Server port (default: 3000)
- `NODE_ENV` - Environment (development/production)
# Updated Fri Nov 14 23:40:30 PST 2025
# Updated Mon Nov 17 10:47:44 PST 2025
# OIDC Test - Mon Nov 17 11:01:49 PST 2025
Sat Nov 22 15:42:50 PST 2025
Mon Nov 24 06:54:56 PST 2025
Mon Nov 24 07:23:19 PST 2025
Mon Nov 24 08:35:15 PST 2025
Mon Nov 24 09:01:22 PST 2025
