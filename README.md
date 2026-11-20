# RedStar

The Modern Python WSGI Framework

**Fast without the fuss.**<br>
**Elegant without the async.**

[English](./README.en.md)

RedStar는 일반 Python 메서드로 HTTP 요청을 처리하는 동기식 웹 프레임워크입니다. `async` / `await` 없이 라우트, 요청 검증, 응답과 확장 기능을 구성할 수 있습니다.

- 경로·쿼리·헤더·본문 입력 검증
- JSON·텍스트·파일 응답, 스트리밍, Server-Sent Events와 WebSocket
- 상태 확인, Metrics, OpenAPI·Swagger UI, 파일 제공 확장
- 기본 Python 서버와 선택형 Gunicorn·Uvicorn 어댑터

## 요구 사항 및 설치

Python 3.9 이상이 필요합니다. 기본 서버는 추가 서버 의존성 없이 설치됩니다.

```shell
python -m pip install py-wsgi-redstar
```

PyPI 배포명은 `py-wsgi-redstar`이고, Python 코드에서는 `RedStar`로 가져옵니다(`from RedStar import Application`).

Gunicorn 또는 Uvicorn 어댑터를 사용할 때 해당 extra를 설치합니다.
두 어댑터 코드는 기본 배포물에 항상 포함되며, extra는 어댑터에 필요한 외부 의존성만 설치합니다.

```shell
python -m pip install "py-wsgi-redstar[Gunicorn]"
python -m pip install "py-wsgi-redstar[Uvicorn]"
```

소스 코드를 수정하고 싶다면 [설치 구성과 개발·배포](./docs/Packaging.md)를 참고하세요.

## 빠른 시작

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

서버를 실행한 뒤 `GET /hello` 요청을 보내면 `Hello, world!`가 반환됩니다. 요청 검증, 응답 스트리밍, 생명주기 훅과 서버 설정은 [상세 매뉴얼](./docs/README.md)을 참고하세요.

## 문서와 릴리즈

- [상세 매뉴얼 (한국어)](./docs/README.md)
- [릴리즈와 변경 내역](https://github.com/yong5eon/RedStar/releases)

라이선스 조건은 저장소의 `LICENSE` 파일을 확인하세요.
