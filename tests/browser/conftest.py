import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from dots_and_dashes.web import create_app


@pytest.fixture
def live_server(settings, clock) -> Iterator[str]:
    """Serve the app on a free local port for the browser to drive."""
    config = uvicorn.Config(
        create_app(settings, clock=clock),
        host="127.0.0.1",
        port=0,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join()
