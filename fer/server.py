"""A simple aiohttp server for health checks."""

from aiohttp import web
from loguru import logger


async def health_check(_request: web.Request) -> web.Response:
    """Health check endpoint to verify the server is running."""
    return web.json_response(
        {"status": "healthy", "details": "Server is running."}, status=200
    )


async def start_health_check_server(host: str, port: int = 8080) -> web.Application:
    """
    Start an aiohttp health check server.

    Args:
        host (str): The host to bind the server to.
        port (int): The port to bind the server to.

    """
    app = web.Application()
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info(f"Health check server started at http://{host}:{port}/health")
