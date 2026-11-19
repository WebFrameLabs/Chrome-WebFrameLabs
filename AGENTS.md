# Project Summary

This repository provides a Chrome desktop devcontainer with a custom Chromer
homepage.

## Maintaining This Summary

When future AI sessions make meaningful project changes or discover important
operational details, they should update this file so later sessions can pick up
the context. Preserve useful existing notes and keep the summary concise.

## Runtime

- `.devcontainer/devcontainer.json` uses the LinuxServer Chrome image.
- `.devcontainer/startup.sh` configures Chrome's homepage and startup policies,
  then starts the custom HTTP servers.
- `.devcontainer/chromer_server.py` serves the workspace's `index.html` on
  `0.0.0.0:43083`.
- `index.html` is the custom homepage loaded by Chrome.
- `.devcontainer/chromer_server.py` also serves the feedback form on
  `0.0.0.0:43084`.

## Ports

- `3000`: Chrome desktop HTTP interface.
- `43083`: Custom Chromer homepage HTTP server.
- `43084`: Private feedback form and submission endpoint, labeled `feedback`.

All three ports are listed in `forwardPorts` in the devcontainer configuration.
After changing port forwarding settings, reopen or rebuild the devcontainer.

## Feedback

- Friends can use the forwarded port labeled `feedback` (43084) to submit
  feedback without getting code-edit access. Share that port's URL with them.
- `POST /api/feedback` validates submissions and stores them privately in
  `/config/chromer-feedback.jsonl`, outside the served workspace.
- Read submissions from the container terminal with
  `cat /config/chromer-feedback.jsonl`. Feedback is not displayed publicly.
- The endpoint accepts optional names up to 80 characters and messages up to
  1,000 characters, allows five submissions per client per minute, and caps
  storage at 1 MiB. Do not request passwords or other sensitive information.
- Feedback forms offer an `app_request` category for suggesting new apps.

## Current Handoff

- The site server was changed from selecting a random port to listening on
  `43083`, matching the configured forwarded port.
- The custom server startup now uses an absolute script path and supports an
  explicit serving directory, so it is independent of the shell's working
  directory.
- The feedback form runs on separate port 43084 so it can be shared
  independently from the homepage.
- The custom homepage also includes a feedback modal that submits to
  `/api/feedback` on port 43083.
- The Toby shortcut on the port 43083 homepage opens port 3000 in a new tab and
  sends its fixed URL to Chrome through the same-origin `/api/open-toby`
  endpoint.
- The Balatro shortcut uses ID `balatro` and opens its Steam store page through
  `/api/open-app`. When adding or renaming a desktop app shortcut, keep its
  `data-id` in `index.html` synchronized with both `APP_URLS` and `APP_LABELS`
  in `.devcontainer/chromer_server.py`; otherwise the endpoint returns HTTP 400.
- The homepage JavaScript and server shortcut lists are loaded into memory, so
  restart the running server (or rebuild the devcontainer) after changing them.
- Chrome startup policy allowlists Toby and common AI websites, but network-
  level restrictions outside Chrome may still apply.
- If port `43083` stops responding, run `bash .devcontainer/startup.sh` from
  the workspace root. It restarts the server when no `chromer_server.py`
  process is running. Verify recovery with
  `curl --fail --max-time 5 http://127.0.0.1:43083/`.
