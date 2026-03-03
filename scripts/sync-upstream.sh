#!/bin/bash
# Sync manobot with upstream nanobot repository
set -e

UPSTREAM_REMOTE="upstream"
UPSTREAM_BRANCH="main"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Manobot Upstream Sync ===${NC}"
echo ""

# Check if upstream remote exists
if ! git remote | grep -q "^${UPSTREAM_REMOTE}$"; then
    echo -e "${YELLOW}Upstream remote not found. Adding it now...${NC}"
    git remote add ${UPSTREAM_REMOTE} https://github.com/HKUDS/nanobot.git
    echo -e "${GREEN}Added upstream remote: https://github.com/HKUDS/nanobot.git${NC}"
fi

echo "Fetching upstream nanobot..."
git fetch ${UPSTREAM_REMOTE}

# Count new commits
NEW_COMMITS=$(git rev-list HEAD..${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} --count 2>/dev/null || echo "0")

if [ "$NEW_COMMITS" -eq 0 ]; then
    echo -e "${GREEN}✓ Already up to date with upstream!${NC}"
    exit 0
fi

echo -e "${YELLOW}Found $NEW_COMMITS new commit(s) from upstream${NC}"
echo ""
echo "New changes:"
echo "─────────────────────────────────────────"
git log HEAD..${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} --oneline --no-decorate | head -20
if [ "$NEW_COMMITS" -gt 20 ]; then
    echo "... and $((NEW_COMMITS - 20)) more"
fi
echo "─────────────────────────────────────────"
echo ""

# Check for potential conflicts
echo "Checking for potential conflicts..."
CONFLICT_FILES=$(git diff --name-only HEAD ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} -- nanobot/config/schema.py pyproject.toml 2>/dev/null || echo "")
if [ -n "$CONFLICT_FILES" ]; then
    echo -e "${YELLOW}Warning: These files may have conflicts:${NC}"
    echo "$CONFLICT_FILES"
    echo ""
fi

read -p "Merge these changes? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Merging upstream/${UPSTREAM_BRANCH}..."
    
    if git merge ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH} -m "Merge upstream nanobot updates"; then
        echo ""
        echo -e "${GREEN}✓ Merged successfully!${NC}"
        echo ""
        echo "Summary:"
        echo "  - Merged $NEW_COMMITS commit(s) from upstream"
        echo "  - Run 'git push' to push changes to your remote"
    else
        echo ""
        echo -e "${RED}Merge conflicts detected!${NC}"
        echo ""
        echo "Resolve conflicts in the following files:"
        git diff --name-only --diff-filter=U
        echo ""
        echo "After resolving:"
        echo "  1. git add <resolved-files>"
        echo "  2. git commit"
        echo "  3. git push"
    fi
else
    echo "Merge cancelled."
fi
