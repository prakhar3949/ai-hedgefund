#!/bin/bash
source ~/clawd/credentials/twitter-creds.sh
bird "$@" --auth-token "$TWITTER_AUTH_TOKEN" --ct0 "$TWITTER_CT0"
