#!/bin/bash
# OpenEvent AI - Quick Update Script
# Run after pushing changes to git
# Usage: ssh root@72.60.135.183 "cd /opt/openevent && ./deploy/update.sh"

set -e

cd /opt/openevent

echo "Pulling latest changes from hostinger-backend..."
git pull origin integration/hostinger-backend

echo "Installing any new dependencies..."
./venv/bin/pip install -r requirements-dev

echo "Restarting service..."
systemctl restart openevent

echo "Done! Checking status..."
systemctl status openevent --no-pager

echo ""
echo "Quick test:"
curl -s http://localhost:8000/api/workflow/health | python3 -m json.tool
