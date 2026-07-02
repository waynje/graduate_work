from gevent import monkey

monkey.patch_all()

from gevent.pywsgi import WSGIServer

from ugc_service.app import create_app
from ugc_service.config import get_settings


def run() -> None:
    settings = get_settings()
    app = create_app(settings)
    http_server = WSGIServer(("0.0.0.0", settings.ugc_api_port), app)
    http_server.serve_forever()


if __name__ == "__main__":
    run()
