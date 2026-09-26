#!/bin/bash

# Simple script to push to Hugging Face without large file history issues

echo "=========================================="
echo "Push to Hugging Face (Clean)"
echo "=========================================="
echo ""

# Configuration
REMOTE_NAME=${1:-hf}
echo "Target remote: $REMOTE_NAME"

# Remember current branch before switching
ORIGINAL_BRANCH=$(git branch --show-current)
if [ -z "$ORIGINAL_BRANCH" ]; then
  ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)
fi
echo "📍 Current branch: $ORIGINAL_BRANCH"

# Create orphan branch with current state (no history)
echo "🔄 Creating clean branch..."
TEMP_BRANCH="hf-clean-$(date +%s)"

git checkout --orphan $TEMP_BRANCH || {
  echo "❌ Failed to create orphan branch"
  exit 1
}

# Add HuggingFace Spaces header to README.md
echo "📝 Adding HuggingFace Spaces header to README.md..."
HF_HEADER="---
title: CUGA Agent
emoji: 🤖
colorFrom: purple
colorTo: blue
sdk: docker
sdk_version: \"4.36\"
app_file: app.py
pinned: false
app_port: 7860
description: Configurable Generalist Agent, leader in AppWorld Benchmark
short_description: Configurable Generalist Agent, leader in AppWorld Benchmark
---

"

# Check if README.md exists
if [ -f "README.md" ]; then
  # Check if header already exists
  if ! grep -q "^---" README.md || ! grep -q "title: CUGA Agent" README.md; then
    # Prepend header to README.md
    echo "$HF_HEADER$(cat README.md)" > README.md
    echo "✅ Added HuggingFace Spaces header to README.md"
  else
    echo "ℹ️  README.md already has HuggingFace Spaces header"
  fi
else
  echo "⚠️  README.md not found, creating with header..."
  echo "$HF_HEADER" > README.md
fi

git add -A
# Remove binary files that HuggingFace doesn't allow
echo "🚫 Excluding binary files from push..."
BINARY_FILE="docs/examples/langflow/CUGA-Langflow-Demo.png"
if git ls-files --cached "$BINARY_FILE" | grep -q .; then
  git rm --cached "$BINARY_FILE" 2>/dev/null || true
  echo "✅ Removed binary file from staging"
fi
git commit --no-verify -m "feat: docker-v1 with optimized frontend

- Optimized webpack bundle from 16MB to 6.67MB
- Added HF Space configuration
- Production build with minification
- All files under 10MB limit" || {
  echo "❌ Failed to commit changes"
  echo "🔄 Returning to original branch: $ORIGINAL_BRANCH"
  # Remove the binary file from working tree if it exists as untracked
  rm -f "$BINARY_FILE" 2>/dev/null || true
  git checkout -f $ORIGINAL_BRANCH
  git branch -D $TEMP_BRANCH
  exit 1
}

echo ""
echo "🚀 Pushing to $REMOTE_NAME/main..."
git push $REMOTE_NAME $TEMP_BRANCH:main --force

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Successfully pushed to Hugging Face!"
  echo "🔄 Returning to original branch: $ORIGINAL_BRANCH"
  # Remove the binary file from working tree if it exists as untracked
  rm -f "$BINARY_FILE" 2>/dev/null || true
  git checkout -f $ORIGINAL_BRANCH
  git branch -D $TEMP_BRANCH
else
  echo ""
  echo "❌ Push failed"
  echo "🔄 Returning to original branch: $ORIGINAL_BRANCH"
  # Remove the binary file from working tree if it exists as untracked
  rm -f "$BINARY_FILE" 2>/dev/null || true
  git checkout -f $ORIGINAL_BRANCH
  git branch -D $TEMP_BRANCH
  exit 1
fi