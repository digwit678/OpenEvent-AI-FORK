# API Key Setup Guide

This guide explains how to securely configure API keys for OpenEvent-AI development.

## Why Keychain?

We use **macOS Keychain** for API key storage because:
- Keys are encrypted at rest by the OS
- Never stored in plaintext files that could be committed
- Controlled by macOS security (Touch ID, password)
- Shared across terminal sessions automatically

**Never commit API keys to git.** Even in `.env` files.

## Quick Setup (macOS)

### 1. Get Your API Keys

- **OpenAI**: https://platform.openai.com/api-keys
- **Google/Gemini**: https://aistudio.google.com/app/apikey

### 2. Store Keys in Keychain

```bash
# OpenAI key (for verbalization - client-facing text)
security add-generic-password -s 'openevent-api-test-key' -a "$USER" -w 'sk-proj-YOUR-OPENAI-KEY'

# Google/Gemini key (for intent/entity extraction)
security add-generic-password -s 'openevent-gemini-key' -a "$USER" -w 'YOUR-GOOGLE-API-KEY'
```

### 3. Verify Keys Are Stored

```bash
# Check OpenAI key exists
security find-generic-password -s 'openevent-api-test-key' -a "$USER" -w

# Check Gemini key exists
security find-generic-password -s 'openevent-gemini-key' -w
```

### 4. Start Development Server

```bash
./scripts/dev/dev_server.sh
```

The script automatically loads keys from Keychain and shows status:
```
==========================================
          API KEY STATUS
==========================================
✓ OPENAI_API_KEY: SET (164 chars)
✓ GOOGLE_API_KEY: SET (39 chars)
------------------------------------------
AGENT_MODE: gemini
DETECTION_MODE: unified
==========================================
```

## Updating Keys

To update an existing key:
```bash
# Delete old key
security delete-generic-password -s 'openevent-api-test-key' -a "$USER"

# Add new key
security add-generic-password -s 'openevent-api-test-key' -a "$USER" -w 'NEW-KEY'
```

## Linux/Windows Setup

For non-macOS systems, use environment variables:

```bash
export OPENAI_API_KEY="sk-proj-..."
export GOOGLE_API_KEY="..."
```

Or create a `.env` file (ensure it's gitignored!):
```bash
cp .env.example .env
# Edit .env with your keys
```

## CI/CD & Production

- **GitHub Actions**: Use repository secrets
- **Production servers**: Use environment variables or secrets manager (AWS Secrets Manager, HashiCorp Vault)
- **Never hardcode keys** in any configuration files

## Hybrid Mode (Default)

OpenEvent uses **hybrid mode** by default:
- **Gemini** for intent/entity extraction (cost-effective)
- **OpenAI** for verbalization (quality for client-facing text)

Both keys are required for hybrid mode. The system enforces this at startup.

## Troubleshooting

### "GOOGLE_API_KEY is not set" Error
```bash
# Check if key exists in Keychain
security find-generic-password -s 'openevent-gemini-key' -w

# If not found, add it:
security add-generic-password -s 'openevent-gemini-key' -a "$USER" -w 'YOUR-KEY'
```

### Key Leaked / Compromised
1. Immediately rotate the key in OpenAI/Google console
2. Update the key in Keychain (see "Updating Keys" above)
3. If committed to git, use `git-filter-repo` to remove from history

### Running Without Keys (Testing)
```bash
AGENT_MODE=stub ./scripts/dev/dev_server.sh
```
This uses mock responses for testing without real API calls.
