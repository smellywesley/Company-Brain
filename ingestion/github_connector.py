"""
GitHub connector for Company Brain.

Fetches repositories, issues, pull requests, PR review comments, and README
files via the GitHub REST API. All text is PII‑redacted and normalised into
the unified document schema.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ingestion.base_connector import BaseConnector, ConnectorRegistry, NormalizedDocument

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


@ConnectorRegistry.register
class GitHubConnector(BaseConnector):
    """Pulls repos, issues, PRs, and README files from GitHub."""

    SOURCE_NAME = "github"

    def __init__(self) -> None:
        self._token: str = ""
        self._client: httpx.Client | None = None

    # ── Lifecycle ───────────────────────────────────────────────────────
    def authenticate(self) -> None:
        self._token = os.getenv("GITHUB_TOKEN", "")
        if not self._token:
            raise EnvironmentError("GITHUB_TOKEN environment variable is not set")
        self._client = httpx.Client(
            base_url=GITHUB_API,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        logger.info("GitHub connector authenticated")

    # ── Data fetching ───────────────────────────────────────────────────
    def fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch repos → issues, PRs, PR comments, and READMEs."""
        assert self._client is not None, "Call authenticate() first"
        raw_items: list[dict[str, Any]] = []

        repos = self._paginate("/user/repos", params={"per_page": 100, "sort": "updated"})
        logger.info("GitHub: found %d repos", len(repos))

        for repo in repos:
            full_name = repo["full_name"]

            # Issues (includes PRs on GitHub API – filter later)
            issues = self._paginate(f"/repos/{full_name}/issues", params={"state": "all", "per_page": 100})
            for issue in issues:
                issue["_repo"] = full_name
                issue["_kind"] = "pull_request" if "pull_request" in issue else "issue"
                raw_items.append(issue)

            # PR review comments
            pr_comments = self._paginate(
                f"/repos/{full_name}/pulls/comments", params={"per_page": 100, "sort": "updated"}
            )
            for comment in pr_comments:
                comment["_repo"] = full_name
                comment["_kind"] = "pr_comment"
                raw_items.append(comment)

            # README
            readme = self._fetch_readme(full_name)
            if readme:
                readme["_repo"] = full_name
                readme["_kind"] = "readme"
                raw_items.append(readme)

        logger.info("GitHub: fetched %d raw items across %d repos", len(raw_items), len(repos))
        return raw_items

    # ── Normalisation ───────────────────────────────────────────────────
    def normalize(self, raw_item: dict[str, Any]) -> NormalizedDocument:
        kind = raw_item.get("_kind", "unknown")
        repo = raw_item.get("_repo", "")

        if kind in ("issue", "pull_request"):
            return self._normalize_issue(raw_item, kind, repo)
        elif kind == "pr_comment":
            return self._normalize_pr_comment(raw_item, repo)
        elif kind == "readme":
            return self._normalize_readme(raw_item, repo)
        else:
            # Fallback
            return NormalizedDocument(
                source="github",
                id=str(raw_item.get("id", "")),
                author=raw_item.get("user", {}).get("login", "unknown"),
                timestamp=raw_item.get("created_at", ""),
                content=self.redact_pii(str(raw_item)),
                doc_type=kind,
                metadata={"repo": repo},
            )

    # ── Private helpers ─────────────────────────────────────────────────
    def _normalize_issue(self, item: dict[str, Any], kind: str, repo: str) -> NormalizedDocument:
        title = item.get("title", "")
        body = item.get("body", "") or ""
        labels = [l.get("name", "") for l in item.get("labels", [])]
        content = f"## {title}\n\n{body}\n\nLabels: {', '.join(labels)}" if labels else f"## {title}\n\n{body}"

        return NormalizedDocument(
            source="github",
            id=str(item["id"]),
            author=item.get("user", {}).get("login", "unknown"),
            timestamp=item.get("created_at", ""),
            content=self.redact_pii(content),
            doc_type=kind,
            sensitivity_level="internal",
            metadata={
                "repo": repo,
                "number": item.get("number"),
                "state": item.get("state"),
                "url": item.get("html_url", ""),
                "labels": labels,
                "comments_count": item.get("comments", 0),
            },
        )

    def _normalize_pr_comment(self, item: dict[str, Any], repo: str) -> NormalizedDocument:
        body = item.get("body", "") or ""
        diff_hunk = item.get("diff_hunk", "") or ""
        content = f"Code review comment:\n\n```diff\n{diff_hunk}\n```\n\n{body}"

        return NormalizedDocument(
            source="github",
            id=str(item["id"]),
            author=item.get("user", {}).get("login", "unknown"),
            timestamp=item.get("created_at", ""),
            content=self.redact_pii(content),
            doc_type="pr_comment",
            sensitivity_level="internal",
            metadata={
                "repo": repo,
                "pull_request_url": item.get("pull_request_url", ""),
                "path": item.get("path", ""),
                "line": item.get("line"),
            },
        )

    def _normalize_readme(self, item: dict[str, Any], repo: str) -> NormalizedDocument:
        import base64

        content_b64 = item.get("content", "")
        try:
            content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:
            content = content_b64

        return NormalizedDocument(
            source="github",
            id=f"readme-{repo}",
            author="repo",
            timestamp="",
            content=self.redact_pii(content),
            doc_type="readme",
            sensitivity_level="public",
            metadata={"repo": repo, "path": item.get("path", "README.md")},
        )

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Follow GitHub's Link‑header pagination."""
        assert self._client is not None
        results: list[dict[str, Any]] = []
        url: str | None = path
        query = dict(params or {})

        while url:
            resp = self._client.get(url, params=query)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            results.extend(resp.json())
            # Parse next link
            link = resp.headers.get("link", "")
            url = None
            query = {}  # params already encoded in the next URL
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break

        return results

    def _fetch_readme(self, full_name: str) -> dict[str, Any] | None:
        assert self._client is not None
        resp = self._client.get(f"/repos/{full_name}/readme")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
