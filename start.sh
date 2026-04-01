#!/bin/bash
mkdir -p config
printf '%s' "$CONFIG_JSON" > config/config.json
printf '%s' "$GOOGLE_CREDENTIALS_JSON" > config/google_credentials.json
python main.py
