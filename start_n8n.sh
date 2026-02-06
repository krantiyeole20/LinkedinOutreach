#!/bin/bash
# n8n Startup Script with Execute Command Enabled
# Location: /Users/krantiy/Documents/Linkedin Automation Project/start_n8n.sh

echo "Starting n8n with Execute Command node enabled..."
echo "=============================================="

# Set environment variables
export NODES_EXCLUDE="[]"
export GENERIC_TIMEZONE="America/New_York"
export TZ="America/New_York"
export EXECUTIONS_TIMEOUT=3600
export N8N_PORT=5678

echo "Configuration:"
echo "  NODES_EXCLUDE: $NODES_EXCLUDE"
echo "  Timezone: $GENERIC_TIMEZONE"
echo "  Port: $N8N_PORT"
echo "=============================================="
echo ""
echo "n8n will be available at: http://localhost:5678"
echo "Press Ctrl+C to stop"
echo ""

# Start n8n
n8n start
