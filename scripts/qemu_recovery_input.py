#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Send real QEMU tablet events; application state is never read or modified."""
import argparse
import json
from pathlib import Path
import socket
import time


def click(endpoint: Path, x: int, y: int, width: int, height: int) -> dict:
    if not 2 <= width <= 16384 or not 2 <= height <= 16384:
        raise ValueError('display dimensions outside supported bounds')
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError('pointer position outside display')
    if not endpoint.is_socket():
        raise ValueError('requires an existing QMP Unix socket')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(str(endpoint))
        with connection.makefile('rwb', buffering=0) as stream:
            if 'QMP' not in json.loads(stream.readline(65537)):
                raise ValueError('unexpected QMP greeting')
            sequence = 0

            def request(name: str, arguments: dict | None = None):
                nonlocal sequence
                sequence += 1
                message = dict(execute=name, id=sequence)
                if arguments is not None:
                    message['arguments'] = arguments
                stream.write(json.dumps(message).encode() + b'\n')
                for _ in range(64):
                    line = stream.readline(65537)
                    if not line or len(line) > 65536:
                        raise ValueError('invalid QMP response size')
                    reply = json.loads(line)
                    if reply.get('id') != sequence:
                        if 'event' not in reply:
                            raise ValueError('unexpected QMP response identity')
                        continue
                    if 'error' in reply:
                        raise RuntimeError(f'QMP {name} failed: {reply["error"]}')
                    return reply['return']
                raise RuntimeError('QMP response exceeded event budget')

            request('qmp_capabilities')
            state = request('query-status')
            if state.get('running') is not True:
                raise ValueError('guest is not running')
            devices = request('query-mice')
            if len(devices) != 1 or devices[0].get('absolute') is not True:
                raise ValueError('requires exactly one absolute tablet input device')
            coordinates = [dict(type='abs', data=dict(axis=axis, value=value)) for axis, value in
                           (('x', x * 32767 // (width - 1)), ('y', y * 32767 // (height - 1)))]
            request('input-send-event', dict(events=coordinates))
            time.sleep(0.2)
            down_sent = False
            try:
                request('input-send-event', dict(events=[dict(type='btn', data=dict(button='left', down=True))]))
                down_sent = True
                time.sleep(0.2)
            finally:
                if down_sent:
                    request('input-send-event', dict(events=[dict(type='btn', data=dict(button='left', down=False))]))
    return dict(qmp=str(endpoint), device=devices[0], position=[x, y], display=[width, height],
                events_submitted=True, application_result_verified=False,
                guest_memory_modified=False, guest_registers_modified=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qmp', type=Path, required=True)
    parser.add_argument('--click', nargs=2, metavar=('X', 'Y'), type=int, required=True)
    parser.add_argument('--width', type=int, default=800)
    parser.add_argument('--height', type=int, default=600)
    args = parser.parse_args()
    print(json.dumps(click(args.qmp, *args.click, args.width, args.height), indent=2))


if __name__ == '__main__':
    main()
