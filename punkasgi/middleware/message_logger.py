"""
Derived from uvicorn (https://github.com/Kludex/uvicorn), distributed under the
following license:

Copyright © 2017-present, Encode OSS Ltd. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

from __future__ import annotations

import logging

from punkasgi._types import ASGI3Application, ASGIReceiveCallable, ASGISendCallable, WWWScope
from punkasgi.logging import TRACE_LOG_LEVEL


PLACEHOLDER_FORMAT = {
    "body": "<{length} bytes>",
    "bytes": "<{length} bytes>",
    "text": "<{length} chars>",
    "headers": "<...>",
}


def message_with_placeholders(message):
    new_message = message.copy()
    for attr in PLACEHOLDER_FORMAT.keys():
        if message.get(attr) is not None:
            content = message[attr]
            placeholder = PLACEHOLDER_FORMAT[attr].format(length=len(content))
            new_message[attr] = placeholder
    return new_message


class MessageLoggerMiddleware:
    def __init__(self, app: ASGI3Application):
        self.task_counter = 0
        self.app = app
        self.logger = logging.getLogger("punkasgi.asgi")

        def trace(message, *args, **kwargs):
            self.logger.log(TRACE_LOG_LEVEL, message, *args, **kwargs)

        self.logger.trace = trace

    async def __call__(self, scope: WWWScope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        self.task_counter += 1

        task_counter = self.task_counter
        client = scope.get("client")
        prefix = "%s:%d - ASGI" % (client[0], client[1]) if client else "ASGI"

        async def inner_receive():
            message = await receive()
            logged_message = message_with_placeholders(message)
            log_text = "%s [%d] Receive %s"
            self.logger.trace(log_text, prefix, task_counter, logged_message)
            return message

        async def inner_send(message):
            logged_message = message_with_placeholders(message)
            log_text = "%s [%d] Send %s"
            self.logger.trace(log_text, prefix, task_counter, logged_message)
            await send(message)

        logged_scope = message_with_placeholders(scope)
        log_text = "%s [%d] Started scope=%s"
        self.logger.trace(log_text, prefix, task_counter, logged_scope)
        try:
            await self.app(scope, inner_receive, inner_send)
        except BaseException as exc:
            log_text = "%s [%d] Raised exception"
            self.logger.trace(log_text, prefix, task_counter)
            raise exc from None
        else:
            log_text = "%s [%d] Completed"
            self.logger.trace(log_text, prefix, task_counter)
