#!/bin/bash
# One-time Git setup for EvampOps. Run from project root: bash scripts/git-setup.sh

set -e
cd "$(dirname "$0")/.."

echo "EvampOps - Git setup"
echo "===================="

# If .git exists but is broken (e.g. failed init), remove it so we can re-init
if [ -d .git ]; then
  if git status >/dev/null 2>&1; then
    echo "Git repo already exists and is valid."
    git status
    exit 0
  else
    echo "Removing broken .git directory..."
    rm -rf .git
  fi
fi

echo "1. Initializing git repository..."
git init

echo "2. Staging files (respecting .gitignore)..."
git add .

echo "3. Checking status..."
git status

echo ""
echo "4. Creating initial commit..."
git commit -m "Phase 1: Foundation - FastAPI backend, React frontend, Settings, encrypted credentials"

echo ""
echo "Done. Your repo is ready."
echo ""
echo "To push to GitHub:"
echo "  1. Create a new repo on GitHub (github.com -> New repository, name: evamp-ops)"
echo "  2. Do NOT initialize with README (we already have one)"
echo "  3. Run:"
echo "     git remote add origin https://github.com/YOUR_USERNAME/evamp-ops.git"
echo "     git branch -M main"
echo "     git push -u origin main"
echo ""
echo "To set your name/email if needed:"
echo "  git config user.name \"Your Name\""
echo "  git config user.email \"your@email.com\""
echo ""
