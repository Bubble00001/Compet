"""
server.py —— HTTP 服务层
=========================

职责：
1. 监听 0.0.0.0:port，接收判题器 POST 的 Request JSON
2. 调用 brain.decide() 得到 (指令集, prompt, executeCmd)
3. 经 validate.sanitize() 清洗后序列化为 Response JSON 返回
4. 全局异常兜底 + 决策超时熔断（超过阈值返回保守合法指令）

启动方式：bash run.sh port（main3.py 调用 serve(port)）
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .brain import decide
from .validate import sanitize

LOGGER = logging.getLogger(__name__)

# 决策超时阈值（秒）。判题器 5s 响应上限，留 0.5s 余量。
DECISION_TIMEOUT_SECONDS = 3.5


class _DecisionTimeout(Exception):
    """决策超时专用异常。"""


class Handler(BaseHTTPRequestHandler):
    """处理单个回合的 POST 请求。"""

    def do_POST(self) -> None:
        """处理判题器下发的状态请求，返回调度指令。"""
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            LOGGER.exception("failed to parse request JSON")
            self._reply(b'{"roleCommandMap":{},"prompt":"","executeCmd":""}')
            return

        try:
            commands, prompt, execute_cmd = self._safe_decide(payload)
        except Exception:
            LOGGER.exception("decision failed for round %s", payload.get("roundNo"))
            commands, prompt, execute_cmd = {}, "", ""

        # 合法性清洗：剔除非法指令，保证输出 100% 合法
        try:
            from .protocol import Turn
            turn = Turn.load(payload)
            commands = sanitize(turn, commands)
        except Exception:
            LOGGER.exception("sanitize failed, using raw commands")

        body = json.dumps(
            {
                "roleCommandMap": {str(k): v for k, v in commands.items()},
                "prompt": prompt or "",
                "executeCmd": execute_cmd or "",
            },
            ensure_ascii=False,
        ).encode("utf-8")

        LOGGER.info(
            "round %s -> %d commands, prompt=%s, cmd=%s",
            payload.get("roundNo"), len(commands),
            bool(prompt), bool(execute_cmd),
        )
        self._reply(body)

    def _safe_decide(
        self, payload: dict[str, Any],
    ) -> tuple[dict[int, dict[str, Any]], str, str]:
        """
        带超时保护地调用 decide。
        超过 DECISION_TIMEOUT_SECONDS 则返回空指令（保守策略）。
        """
        result: list[tuple[dict[int, dict[str, Any]], str, str]] = []
        error: list[BaseException] = []

        def runner() -> None:
            try:
                result.append(decide(payload))
            except BaseException as exc:  # noqa: BLE001
                error.append(exc)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(timeout=DECISION_TIMEOUT_SECONDS)

        if thread.is_alive():
            LOGGER.error(
                "decision timeout after %ss for round %s",
                DECISION_TIMEOUT_SECONDS, payload.get("roundNo"),
            )
            return {}, "", ""
        if error:
            raise error[0]
        if result:
            return result[0]
        return {}, "", ""

    def _reply(self, body: bytes) -> None:
        """发送 HTTP 响应。"""
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """静默默认 access log，避免污染 stdout。"""
        return


def serve(port: int) -> None:
    """启动 HTTP 服务，阻塞运行。"""
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    LOGGER.info("listening on 0.0.0.0:%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("server stopped by user")
    finally:
        server.server_close()
