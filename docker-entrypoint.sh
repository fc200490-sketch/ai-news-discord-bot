#!/bin/sh
set -e

# Fly mounts the volume as root:root. Hand ownership to the bot user
# on first boot so SQLite + cache files can be written without privileges.
if [ -d /data ]; then
    chown -R bot:bot /data || true
fi

exec gosu bot "$@"
