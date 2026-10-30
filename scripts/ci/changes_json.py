#!/usr/bin/env python3
# Called by the gitlab CI pages job after each push to master.
# Writes the latest commit and the recent commits of a git ref as json, published on gitlab pages, so the
# update check and the what's new page work without git and without the rate limited gitlab api.
# Usage: changes_json.py <ref> <branch> <output file> [count]

import json
import subprocess
import sys

# same fields and layout as lazylibrarian.versioncheck.git_commits, title last so a separator stays in it
LOG_FORMAT = '--format=%H%x1f%h%x1f%cI%x1f%P%x1f%an%x1f%s'


def read_commits(ref: str, count: int) -> list[dict]:
    # topo order keeps the commits of a merged branch together, however old, rather than by date
    out = subprocess.run(['git', 'log', '-z', '--topo-order', LOG_FORMAT, '-n', str(count), ref], check=True,
                         capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    commits = []
    for record in out.split('\0'):
        fields = record.split('\x1f', 5)
        if len(fields) == 6:
            commits.append({'id': fields[0], 'short_id': fields[1], 'committed_date': fields[2],
                            'parent_ids': fields[3].split(), 'author_name': fields[4], 'title': fields[5]})
    return commits


def main(args: list[str]) -> int:
    if len(args) not in (3, 4):
        print('Usage: changes_json.py <ref> <branch> <output file> [count]', file=sys.stderr)
        return 2
    ref, branch, output = args[:3]
    count = int(args[3]) if len(args) == 4 else 500
    commits = read_commits(ref, count)
    if not commits:
        print(f'No commits found for {ref}', file=sys.stderr)
        return 1
    with open(output, 'w', encoding='utf-8') as f:
        json.dump({'branch': branch, 'latest': commits[0]['id'], 'commits': commits}, f, ensure_ascii=False)
    print(f'{output}: {len(commits)} commits of {branch}, latest {commits[0]["short_id"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
