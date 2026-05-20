from __future__ import annotations

import httpx


def new_http_client(follow_redirects: bool = False) -> httpx.Client:
    return httpx.Client(
        timeout=25,
        follow_redirects=follow_redirects,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            )
        },
    )
