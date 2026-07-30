# Local Postgres dumps live here (gitignored).
# daily/   — last 7 days (evamp_ops_YYYY-MM-DD.dump)
# monthly/ — 1 file (evamp_ops_YYYY-MM.dump), created on first backup of each month
# logs/    — backup.log + launchd output
#
# Run:  bash scripts/backup-postgres.sh
# Schedule (macOS): see scripts/com.evampops.postgres-backup.plist
