#!/bin/bash
mkdir -p config
echo "$CONFIG_JSON" > config/config.json
echo "$GOOGLE_CREDENTIALS_JSON" > config/google_credentials.json
python main.py
