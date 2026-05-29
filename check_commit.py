#!/usr/bin/env python3
"""Show changed files and content for a given commit hash."""

import argparse
import os
import subprocess
import sys


def run_git(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        print(f"git error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def is_root_commit(commit, cwd):
    result = subprocess.run(
        ["git", "rev-parse", f"{commit}^"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode != 0


def main():
    parser = argparse.ArgumentParser(description="Check commit changes")
    parser.add_argument("commit", help="Commit hash to inspect")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    commit = args.commit

    # Verify commit exists
    verify = subprocess.run(
        ["git", "cat-file", "-t", commit],
        cwd=script_dir,
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0 or verify.stdout.strip() != "commit":
        print(f"Invalid commit: {commit}", file=sys.stderr)
        sys.exit(1)

    root = is_root_commit(commit, script_dir)

    # Get file change statuses
    if root:
        diff_stat = run_git(
            ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", commit],
            script_dir,
        )
    else:
        diff_stat = run_git(
            ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", f"{commit}^", commit],
            script_dir,
        )

    created = []
    deleted = []
    updated = []

    for line in diff_stat.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        filepath = parts[-1]  # handles renames: R100\told\tnew
        if status.startswith("A"):
            created.append(filepath)
        elif status.startswith("D"):
            deleted.append(filepath)
        elif status.startswith("R"):
            updated.append(filepath)
        else:
            updated.append(filepath)

    if created:
        print("=" * 60)
        print("CREATED FILES")
        print("=" * 60)
        for f in created:
            print(f"  + {f}")

    if deleted:
        print()
        print("=" * 60)
        print("DELETED FILES")
        print("=" * 60)
        for f in deleted:
            print(f"  - {f}")

    if updated:
        print()
        print("=" * 60)
        print("UPDATED FILES")
        print("=" * 60)
        for f in updated:
            print(f"\n  >> {f}")
            print("  " + "-" * 50)
            if root:
                diff = run_git(
                    ["git", "show", "--format=", "-p", commit, "--", f],
                    script_dir,
                )
            else:
                diff = run_git(
                    ["git", "diff", f"{commit}^", commit, "--", f],
                    script_dir,
                )
            for diff_line in diff.splitlines():
                print(f"  {diff_line}")
            print("  " + "-" * 50)

    if not created and not deleted and not updated:
        print("No changes found in this commit.")


if __name__ == "__main__":
    main()
