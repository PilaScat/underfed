from __future__ import annotations

from underfed.dispatcharr import Client, local_path


class Pages(Client):
    def __init__(self, pages: dict[str, object]) -> None:
        super().__init__("http://127.0.0.1:9191", "key")
        self.pages = pages
        self.requested: list[str] = []

    def _request(self, path: str, method: str = "GET") -> object:
        self.requested.append(path)
        return self.pages[path]


def test_every_page_of_a_paginated_answer_is_read():
    client = Pages(
        {
            "/api/channels/channels/?page_size=500": {
                "results": [{"uuid": "a"}],
                "next": "http://dispatcharr.example/api/channels/channels/?page=2&page_size=500",
            },
            "/api/channels/channels/?page=2&page_size=500": {
                "results": [{"uuid": "b"}],
                "next": None,
            },
        }
    )
    rows = client._collect("/api/channels/channels/?page_size=500")
    assert [row["uuid"] for row in rows] == ["a", "b"]
    assert client.requested[1] == "/api/channels/channels/?page=2&page_size=500"


def test_a_plain_list_is_one_page():
    client = Pages({"/x": [{"id": 1}, "noise", {"id": 2}]})
    assert client._collect("/x") == [{"id": 1}, {"id": 2}]


def test_a_next_link_pointing_back_does_not_loop():
    client = Pages({"/x": {"results": [{"id": 1}], "next": "http://h/x"}})
    assert client._collect("/x") == [{"id": 1}]
    assert client.requested == ["/x"]


def test_the_next_link_keeps_only_path_and_query():
    assert local_path("https://proxy.example:8443/api/s/?page=3") == "/api/s/?page=3"
    assert local_path("/api/s/") == "/api/s/"
    assert local_path(None) == ""
