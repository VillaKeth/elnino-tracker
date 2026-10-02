#!/bin/sh
# Refresh the El Nino tracker, then publish its pages as the site on GitHub
# Pages: publish.bat's twin for Linux and macOS, and what the hourly run on
# GitHub calls (.github/workflows/live.yml). See publish.py, and "The live
# site" in the README.
#
#   ./publish.sh                 run, then publish to the site
#   ./publish.sh --remote URL    ...to another repository (publish.py's options)
#
# A run is published when track.py says it ran: 0 (nothing above WATCH open),
# 1 (WARNING or CRITICAL alerts open) or 3 (some feeds failed), which its pages
# say. Any other exit publishes nothing. publish.sh then exits with the run's
# own code once it is published, 2 when the tracker did not run, and 4 when it
# ran but publishing failed.
cd "$(dirname "$0")" || exit 2
python3 track.py --brief
code=$?
case $code in
  0 | 1 | 3) ;;
  *)
    echo "The tracker did not run, so nothing was published. Check the messages above." >&2
    exit 2
    ;;
esac
if ! python3 publish.py "$@"; then
  echo "The tracker ran, but publishing failed. Check the messages above." >&2
  exit 4
fi
exit "$code"
