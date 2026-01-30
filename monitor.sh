#!/bin/bash

echo "📊 Docker Container Status"
echo "=========================="
echo ""

echo "🐳 Running Containers:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"

echo ""
echo "📦 All Containers (including stopped):"
TOTAL=$(docker ps -a | wc -l)
RUNNING=$(docker ps | wc -l)
echo "Total: $((TOTAL - 1))"
echo "Running: $((RUNNING - 1))"
echo "Stopped: $((TOTAL - RUNNING))"

echo ""
echo "💾 Disk Usage:"
docker system df

echo ""
echo "🎯 Form Filler Container:"
if docker ps -a --format '{{.Names}}' | grep -q "form-filler-app"; then
    STATUS=$(docker ps -a --filter "name=form-filler-app" --format "{{.Status}}")
    echo "✅ Container exists - Status: $STATUS"
else
    echo "❌ Container not found"
fi

echo ""
echo "💻 System Resources:"
free -h | grep "Mem:"
df -h | grep -E "/$|/var"