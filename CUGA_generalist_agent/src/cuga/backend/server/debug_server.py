from cuga.config import settings
from main import app


def main():
    """Main entry point for the server"""
    import uvicorn

    # Get the port from settings
    port = settings.server_ports.demo

    uvicorn.run(app, host="0.0.0.0", port=port, reload=False, log_level="info")


if __name__ == "__main__":
    # if getattr(settings.advanced_features, "use_extension", False):
    main()
