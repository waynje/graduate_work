#!/bin/sh
set -e

# Keep migration history consistent with a preloaded DB dump where
# admin migrations may already exist before the custom users app history.
python manage.py shell -c "from django.db import connection; from django.db.migrations.recorder import MigrationRecorder; recorder = MigrationRecorder(connection); qs = recorder.migration_qs.filter(app='users', name='0001_initial'); (qs.exists() or recorder.record_applied('users', '0001_initial'))"

python manage.py migrate --noinput

python manage.py runserver 0.0.0.0:8080
