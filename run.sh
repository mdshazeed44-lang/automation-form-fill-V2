#!/bin/bash

set -e

PROJECT_DIR="/opt/form-filler"
CONTAINER_NAME="form-filler-app"

echo "🚀 Starting Form Filler Automation"
echo "=================================="
echo "Time: $(date)"
echo ""

cd "$PROJECT_DIR"

# Step 1: Cleanup old container
echo "🧹 Cleaning up old containers..."
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
docker container prune -f

# Step 2: Check resources
echo ""
echo "💾 System Resources Before:"
free -h | grep "Mem:" || true
docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}" 2>/dev/null || echo "No containers running"

# Step 3: Run container
echo ""
echo "🚀 Starting container..."
docker-compose up --abort-on-container-exit --remove-orphans

# Step 4: Cleanup after completion
echo ""
echo "🧹 Cleaning up after completion..."
docker-compose down --remove-orphans
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Step 5: Final check
echo ""
echo "✅ Execution Complete"
echo "💾 System Resources After:"
free -h | grep "Mem:" || true

# Step 6: Container count check
CONTAINER_COUNT=$(docker ps -a | wc -l)
echo ""
echo "📊 Total containers: $((CONTAINER_COUNT - 1))"

if [ $((CONTAINER_COUNT - 1)) -gt 5 ]; then
    echo "⚠️ WARNING: Too many containers. Running full cleanup..."
    docker system prune -af
fi

echo ""
echo "🎉 Done at $(date)"
```

---

#### **4. `.dockerignore`**
```
venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
*.so
*.egg
*.egg-info
dist/
build/
*.log
debug_*.png
.git/
.gitignore
README.md
.env