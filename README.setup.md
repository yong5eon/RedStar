# RedStar

The Modern Python WSGI Framework

RedStar is a synchronous Python web framework for handling HTTP requests with ordinary methods. Python 3.9 or later is required.

## Installation

```shell
python -m pip install py-wsgi-redstar
```

The PyPI distribution name is `py-wsgi-redstar`, and you import it in Python as `RedStar` (`from RedStar import Application`).

The built-in Python HTTP server requires no additional server dependency. The Gunicorn and Uvicorn adapter sources are always included; the following extras install only the external dependencies each adapter needs:

```shell
python -m pip install "py-wsgi-redstar[Gunicorn]"
python -m pip install "py-wsgi-redstar[Uvicorn]"
```

Install the desired adapter extra when needed.

## Quick start

Save this example as `app.py` and run `python app.py`.

```python
from RedStar import Application, Request, RequestRunner
from RedStar.Adapter.Implements.Python import Server
from RedStar.Responses import ResponseText


class Hello(RequestRunner, method='GET', url='/hello'):
  def run(self, request: Request):
    return ResponseText('Hello, world!')


application = Application()
application.add(Hello)
Server('127.0.0.1', 8000, application).run()
```

The server listens on `127.0.0.1:8000`. A `GET /hello` request returns `Hello, world!`.

## License

See the `LICENSE` file included with the source distribution for license terms.
