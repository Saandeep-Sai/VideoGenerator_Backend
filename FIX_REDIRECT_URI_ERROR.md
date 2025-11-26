# 🔧 Fix: Error 400 - invalid_request (Redirect URI Mismatch)

**The Problem:** Google OAuth doesn't recognize the redirect URI used by your script.

**Root Cause:** Your `client_secret.json` has:

```json
"redirect_uris":["http://localhost"]
```

But the headless script generates a URL with a specific port like `http://localhost:8080` or `http://localhost:0` (random port).

---

## ✅ Solution 1: Use generate_token_local.py (Recommended)

This script works **100%** on your local Windows machine because it uses the browser naturally:

```bash
# On your Windows machine (in VS Code terminal or PowerShell)
cd d:\Video_Generator\backend
python3 generate_token_local.py
```

**What happens:**

1. Browser opens automatically
2. You log in to Google
3. Grant permissions
4. `token.json` is created in `d:\Video_Generator\backend\`
5. You copy it to your instance via SCP

**This avoids the redirect URI issue completely!**

---

## 🔧 Solution 2: Fix Google Cloud Console (If you want headless to work)

If you want to use the headless script on your instance, update your Google Cloud settings:

### Step 1: Go to Google Cloud Console

1. Visit: https://console.cloud.google.com/
2. Select project: **videodemo-52cdd**
3. Go to: **APIs & Services** → **Credentials**
4. Find your OAuth 2.0 Client ID (labeled "Desktop app" or "Installed application")
5. Click to edit it

### Step 2: Add Redirect URIs

In the "Authorized redirect URIs" section, add:

- `http://localhost` (already there)
- `http://localhost:8080` (add this)
- `http://localhost:0` (add this - for random port)
- `http://localhost:80` (optional)
- `urn:ietf:wg:oauth:2.0:oob` (for manual code entry)

### Step 3: Save

Click "Save" and wait a few seconds for changes to propagate.

---

## 🚀 Quickest Solution: Use Option 1

```bash
# On your LOCAL machine
python3 generate_token_local.py

# Follow browser prompts (automatic - no copy/paste needed)

# Copy to instance
scp token.json ubuntu@<instance-ip>:~/VideoGenerator_Backend/

# Done! Instance can now upload to YouTube
```

**This takes 2 minutes and works 100% of the time.**

---

## 📝 Detailed Error Analysis

The error occurs because:

1. **User's Client Secret has:**

   ```json
   "redirect_uris": ["http://localhost"]
   ```

2. **Headless script tries to use:**

   ```
   http://localhost:0  (or random port)
   OR
   http://localhost:8080
   ```

3. **Google rejects it:**

   ```
   Error 400: invalid_request
   Reason: redirect_uri doesn't match registered URIs
   ```

4. **Solution:** Either:
   - Use a script that respects the registered URI
   - OR update Google Cloud Console to accept more URIs
   - OR use the local machine (has browser, automatic handling)

---

## 🎯 My Recommendation

**Just use this on your LOCAL machine:**

```bash
python3 generate_token_local.py
```

It's:

- ✅ Simplest
- ✅ Fastest
- ✅ Most reliable
- ✅ Zero redirect URI issues
- ✅ Automatic browser handling

Then copy the resulting `token.json` to your instance.

---

**Ready? Try: `python3 generate_token_local.py` on your Windows machine!**
