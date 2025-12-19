# Cloudflare API Token Setup Guide

## ⚠️ Important: Token Permissions

Cloudflare API tokens require **specific, scoped permissions**. "Read all resources" is not sufficient - you need to configure the token with the correct permissions AND scope it to your zone(s).

## 📋 Required Permissions

Your API token needs these **exact permissions**:

### Zone Permissions:
1. **Zone.Zone** - Read
2. **Zone.Analytics** - Read  
3. **Zone.DNS** - Edit
4. **Zone.Firewall Services** - Edit
5. **Zone.Cache Purge** - Purge

### Account Permissions (Optional, for account-level operations):
- **Account.Account Settings** - Read (optional)

## 🎯 Token Scope Configuration

**CRITICAL**: After setting permissions, you MUST configure the scope:

### Option 1: Single Zone (Recommended)
1. Under "Zone Resources", select **"Include - Specific zone"**
2. Select your zone from the dropdown
3. Click "Continue to summary"

### Option 2: All Zones (If you manage multiple zones)
1. Under "Zone Resources", select **"Include - All zones"**
2. Click "Continue to summary"

## 📝 Step-by-Step Token Creation

1. Go to: https://dash.cloudflare.com/profile/api-tokens
2. Click **"Create Token"**
3. Click **"Create Custom Token"**
4. Configure:

   **Token Name**: `PocketCF Bot` (or any name you prefer)

   **Permissions**:
   - Zone → Zone → Read
   - Zone → Analytics → Read
   - Zone → DNS → Edit
   - Zone → Firewall Services → Edit
   - Zone → Cache Purge → Purge

   **Zone Resources**:
   - Select **"Include - Specific zone"**
   - Choose your zone from the dropdown

5. Click **"Continue to summary"**
6. Review and click **"Create Token"**
7. **Copy the token immediately** (you won't see it again!)
8. Paste it into your `.env` file as `CLOUDFLARE_API_TOKEN`

## ✅ Verification

After creating the token, run `/test_config` in your Telegram bot to verify:
- Token is valid (should show ✅)
- Zone is accessible (should show ✅)
- All permissions are working

## 🔍 Troubleshooting

### Error: "401 Unauthorized"
- Token is invalid or expired
- Token was copied incorrectly
- Token is for a different Cloudflare account

**Solution**: Create a new token and copy it carefully

### Error: "403 Forbidden - Zone access forbidden"
- Token doesn't have Zone.Zone (Read) permission
- Token is not scoped to your zone
- Token is scoped to wrong zone

**Solution**: 
1. Check token permissions include "Zone.Zone - Read"
2. Verify token scope includes your zone
3. Create a new token with correct scope

### Error: "404 Zone not found"
- Zone ID is incorrect
- Zone was deleted
- Zone is in a different account

**Solution**: 
1. Get Zone ID from Cloudflare Dashboard → Your Domain → Overview (right sidebar)
2. Verify zone exists and is active
3. Check you're using the correct Cloudflare account

## 📸 Visual Guide

```
Token Creation Flow:
┌─────────────────────────────────────┐
│ 1. Create Custom Token              │
├─────────────────────────────────────┤
│ 2. Set Permissions:                 │
│    ✓ Zone.Zone (Read)               │
│    ✓ Zone.Analytics (Read)          │
│    ✓ Zone.DNS (Edit)                │
│    ✓ Zone.Firewall Services (Edit)  │
│    ✓ Zone.Cache Purge (Purge)       │
├─────────────────────────────────────┤
│ 3. Set Zone Resources:             │
│    ⚠️ IMPORTANT:                    │
│    → Include - Specific zone        │
│    → Select your zone               │
├─────────────────────────────────────┤
│ 4. Create Token                     │
│ 5. Copy Token (save immediately!)   │
└─────────────────────────────────────┘
```

## 🔐 Security Best Practices

1. **Never share your API token** - treat it like a password
2. **Use specific zone scope** - don't use "All zones" unless necessary
3. **Rotate tokens periodically** - create new tokens every 6-12 months
4. **Revoke unused tokens** - delete old tokens you're not using
5. **Don't commit tokens to git** - ensure `.env` is in `.gitignore`

## 📚 Official Documentation

- [Cloudflare API Tokens](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
- [API Token Permissions](https://developers.cloudflare.com/fundamentals/api/get-started/permissions/)
- [Zone Resources](https://developers.cloudflare.com/fundamentals/api/get-started/zone-api/)

