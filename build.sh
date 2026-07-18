#!/usr/bin/env bash
# Vercel build script: substitutes __API_BASE_URL__ in index.html with the actual
# Render backend URL from the environment variable RENDER_BACKEND_URL.
# Set RENDER_BACKEND_URL in Vercel Project Settings > Environment Variables.

set -e

BACKEND_URL="${RENDER_BACKEND_URL:-}"

if [ -n "$BACKEND_URL" ]; then
  echo "✅ Injecting RENDER_BACKEND_URL: $BACKEND_URL"
  # Replace the placeholder in the HTML file
  sed -i "s|__API_BASE_URL__|${BACKEND_URL}|g" frontend/index.html
else
  echo "⚠️  RENDER_BACKEND_URL not set — falling back to same-origin Vercel serverless API"
fi
