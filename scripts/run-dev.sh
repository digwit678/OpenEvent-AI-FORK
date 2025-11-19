#!/bin/sh
set -e
echo "Starting backend..."
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 &
cd ..
echo "Starting frontend..."
cd atelier-ai-frontend
npm run dev &
