# RedStar

The Modern Python WSGI Framework

**Fast without the fuss.**<br>
**Elegant without the async.**

[한국어](./README.md)

RedStar is a synchronous web framework for handling HTTP requests with ordinary Python methods. Configure routes, request validation, responses, and extensions without `async` / `await`.

- Validation for path, query, header, and body inputs
- JSON, text, and file responses; streaming, Server-Sent Events, and WebSocket
- Extensions for status checks, metrics, OpenAPI, Swagger UI, and file serving
- Built-in Python server with optional Gunicorn and Uvicorn adapters

## Requirements and installation

Requires Python 3.9 or later. The built-in server is available without extra server dependencies.

```shell
python -m pip install py-wsgi-redstar
```

The PyPI distribution name is `py-wsgi-redstar`, and you import it in Python as `RedStar` (`from RedStar import Application`).

Install an extra when using the corresponding Gunicorn or Uvicorn adapter.
Both adapters' code is always included in the distribution; each extra only installs that adapter's external dependencies.

```shell
python -m pip install "py-wsgi-redstar[Gunicorn]"
python -m pip install "py-wsgi-redstar[Uvicorn]"
```

To modify the source code, see [installation layout, development and distribution](./docs/Packaging.en.md).

## Quick start

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

After starting the server, send a `GET /hello` request to receive `Hello, world!`. See the [detailed guide](./docs/README.en.md) for request validation, streaming responses, lifecycle hooks, and server configuration.

## Documentation and releases

- [Detailed guide (English)](./docs/README.en.md)
- [Releases and change history](https://github.com/yong5eon/RedStar/releases)

See the repository's `LICENSE` file for license terms.
