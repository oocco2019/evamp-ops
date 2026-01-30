# Git & GitHub Setup

The project is ready for version control. Run these in your own terminal (Cursor’s environment can’t run git for you).

## One-time setup (local repo + first commit)

From the project root:

```bash
cd /Users/marius/evamp-ops
bash scripts/git-setup.sh
```

That will:
- `git init`
- `git add .` (using existing `.gitignore`, so `.env` and secrets stay untracked)
- `git commit -m "Phase 1: Foundation - ..."`

## Push to GitHub

1. **Create a new repo on GitHub**
   - Go to https://github.com/new
   - Repository name: `evamp-ops` (or whatever you prefer)
   - Leave “Initialize with README” **unchecked**
   - Choose **Private** if you want the repo hidden (recommended for an app with API keys and business logic)
   - Create repository

2. **Add remote and push** (replace `YOUR_USERNAME` with your GitHub username):

   ```bash
   cd /Users/marius/evamp-ops
   git remote add origin https://github.com/YOUR_USERNAME/evamp-ops.git
   git branch -M main
   git push -u origin main
   ```

3. If GitHub asks for auth, use a **Personal Access Token** (Settings → Developer settings → Personal access tokens) as the password, or set up SSH and use the SSH URL for `origin`.

## Optional: set your name/email for this repo

```bash
cd /Users/marius/evamp-ops
git config user.name "Your Name"
git config user.email "your@email.com"
```

Run these before the first commit if you want this repo to use a specific identity.

## What’s ignored (never committed)

`.gitignore` already excludes:
- `.env` (secrets)
- `node_modules/`, `__pycache__/`, `.venv/`
- Database files, logs, build output

So you can safely run `git add .` and push; secrets stay local.
