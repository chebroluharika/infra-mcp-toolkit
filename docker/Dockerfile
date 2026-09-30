# Dockerfile for Frontend - Multi-stage Optimized Build
# QE Agentic Dashboard - React Frontend
# Optimized for smaller image size with multi-stage build
#
# Usage: docker build -t qe-dashboard-frontend .

# Stage 1: Build stage - Node.js for building React app
FROM node:18-alpine AS builder

# Install pinned npm version
RUN npm install -g npm@10.5.0

# Create non-root user for build stage
RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001

WORKDIR /app

# Give ownership of /app to nodejs user
RUN chown -R nodejs:nodejs /app

# Switch to non-root user
USER nodejs

# Copy package files with proper ownership
COPY --chown=nodejs:nodejs package*.json ./

# Install dependencies
RUN npm install && npm cache clean --force

# Copy application code with proper ownership
COPY --chown=nodejs:nodejs . .

# Build the application
RUN npm run build

# Clean up source maps and unnecessary files
RUN find build -name '*.map' -delete && \
    rm -rf node_modules src public

# Stage 2: Production stage - Minimal nginx image
FROM nginx:alpine AS production

# Remove default nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets from builder
COPY --from=builder /app/build /usr/share/nginx/html

# Copy nginx configuration (owned by nginx user so USER nginx below can read it)
COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf

# Create nginx cache (incl. API proxy cache) and pid directories with proper permissions
RUN mkdir -p /var/cache/nginx/api_cache /var/run && \
    chown -R nginx:nginx /var/cache/nginx /var/run /etc/nginx/conf.d && \
    chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html && \
    chmod 644 /etc/nginx/conf.d/default.conf && \
    touch /var/run/nginx.pid && \
    chown nginx:nginx /var/run/nginx.pid

# Remove unnecessary files
RUN rm -rf /var/cache/apk/*

# Run as non-root user
USER nginx

# Expose non-privileged port
EXPOSE 8080

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
