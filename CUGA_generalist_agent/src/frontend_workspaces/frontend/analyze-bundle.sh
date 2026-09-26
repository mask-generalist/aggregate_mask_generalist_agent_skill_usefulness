#!/bin/bash

echo "==================================="
echo "Frontend Bundle Size Analysis"
echo "==================================="
echo ""

cd "$(dirname "$0")/dist" || exit 1

echo "📦 Total Distribution Size:"
du -sh . | awk '{print "   " $1}'
echo ""

echo "📊 JavaScript Bundles:"
echo "   (excluding static files)"
TOTAL_SIZE=$(find . -name "*.js" ! -name "tailwind.js" ! -name "background.js" -type f | xargs du -ck | tail -1 | awk '{print $1}')
TOTAL_MB=$(echo "scale=2; $TOTAL_SIZE / 1024" | bc)
echo "   Total: ${TOTAL_MB} MB"
echo ""

echo "🔝 Top 10 Largest Files:"
find . -name "*.js" ! -name "tailwind.js" ! -name "background.js" -type f -exec du -h {} + | sort -rh | head -10 | awk '{printf "   %-8s %s\n", $1, $2}'
echo ""

echo "📂 Breakdown by Category:"
echo ""

echo "   Carbon AI:"
CARBON_AI=$(find . -name "carbon-ai*.js" -type f | xargs du -ck 2>/dev/null | tail -1 | awk '{print $1}')
CARBON_AI_MB=$(echo "scale=2; $CARBON_AI / 1024" | bc)
CARBON_AI_COUNT=$(find . -name "carbon-ai*.js" -type f | wc -l | tr -d ' ')
echo "      ${CARBON_AI_MB} MB across ${CARBON_AI_COUNT} chunks"

echo "   Carbon Icons:"
CARBON_ICONS=$(find . -name "carbon-icons*.js" -type f | xargs du -ck 2>/dev/null | tail -1 | awk '{print $1}')
CARBON_ICONS_KB=$(echo "scale=0; $CARBON_ICONS" | bc)
CARBON_ICONS_COUNT=$(find . -name "carbon-icons*.js" -type f | wc -l | tr -d ' ')
echo "      ${CARBON_ICONS_KB} KB across ${CARBON_ICONS_COUNT} chunks"

echo "   React Vendor:"
REACT=$(find . -name "react-vendor*.js" -type f | xargs du -ck 2>/dev/null | tail -1 | awk '{print $1}')
REACT_KB=$(echo "scale=0; $REACT" | bc)
echo "      ${REACT_KB} KB"

echo "   Other Vendors:"
VENDORS=$(find . -name "vendors-*.js" -type f | xargs du -ck 2>/dev/null | tail -1 | awk '{print $1}')
VENDORS_MB=$(echo "scale=2; $VENDORS / 1024" | bc)
VENDORS_COUNT=$(find . -name "vendors-*.js" -type f | wc -l | tr -d ' ')
echo "      ${VENDORS_MB} MB across ${VENDORS_COUNT} chunks"

echo "   Main App:"
MAIN=$(find . -name "main-*.js" -type f | xargs du -ck 2>/dev/null | tail -1 | awk '{print $1}')
MAIN_KB=$(echo "scale=0; $MAIN" | bc)
MAIN_COUNT=$(find . -name "main-*.js" -type f | wc -l | tr -d ' ')
echo "      ${MAIN_KB} KB across ${MAIN_COUNT} chunks"

echo ""
echo "==================================="

