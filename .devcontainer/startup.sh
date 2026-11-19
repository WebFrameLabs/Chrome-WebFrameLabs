#!/usr/bin/env bash
set -eu

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
workspace_dir=$(cd "$script_dir/.." && pwd)

mkdir -p /defaults /etc/opt/chrome/policies/managed
index_file=$(find /workspaces -name index.html -print -quit)
if [ -z "$index_file" ]; then
    echo "Could not find the Chromer index.html under /workspaces" >&2
    exit 1
fi
ln -sf "$index_file" /defaults/index.html

if ! grep -q "alt_backtick_script" /defaults/index.html; then
    cat >> /defaults/index.html <<'HTML'
<script id="alt_backtick_script">window.addEventListener("keydown",function(e){if(e.altKey&&e.key==="`"){e.preventDefault();window.open("chrome://newtab","_blank");}});</script>
HTML
fi

cat > /etc/opt/chrome/policies/managed/custom_start_page.json <<'JSON'
{
  "HomepageLocation": "file:///defaults/index.html",
  "NewTabPageLocation": "file:///defaults/index.html",
  "RestoreOnStartup": 1,
  "URLAllowlist": [
    "https://toby.booksforschool.online",
    "https://chatgpt.com",
    "https://claude.ai",
    "https://gemini.google.com",
    "https://copilot.microsoft.com",
    "https://perplexity.ai"
  ],
  "DefaultSearchProviderEnabled": true,
  "DefaultSearchProviderSearchURL": "https://www.google.com/search?q={searchTerms}&sourceid=chrome&ie=UTF-8&safe=off&udm=14",
  "DefaultSearchProviderSuggestURL": "https://www.google.com/complete/search?output=chrome&q={searchTerms}",
  "DefaultSearchProviderName": "Google"
}
JSON

if ! pgrep -f "[c]hromer_server.py" >/dev/null; then
    nohup python3 "$script_dir/chromer_server.py" --directory "$workspace_dir" \
        > /tmp/chromer-http.log 2>&1 </dev/null &
fi
