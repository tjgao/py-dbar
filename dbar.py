#!/usr/bin/env python3
import asyncio
import signal
import time
import os, sys
import argparse
import subprocess

fields_cfg = [
    {
        "name": "﬙  ",
        "cmd": "free -h | awk '/^Mem/ { print $3\"/\"$2 }' | sed s/i//g",
        "interval": 30,
        "signal": 0,
    },
    {"name": "", "cmd": "date '+%a %b %d %I:%M%p'", "interval": 10, "signal": 0},
]


NOT_AVAILABLE = "ERROR N/A"
PID_FILE = "/tmp/_dwm_dbar.pid"


class DWMStatusBar:
    def __init__(self, cfg, loop):
        self.fields = cfg
        self.loop = loop
        self.ppid = None
        self._prepare()

    def _prepare(self):
        attempt = 5
        while not self.ppid and attempt > 0:
            try:
                self.ppid = int(subprocess.check_output('pgrep dwm', shell=True))
            except:
                atempt -= 1
                time.sleep(1)
                continue
        if not self.ppid:
            sys.exit()

        for f in self.fields:
            if f["interval"] > 0:
                f["longrunning"] = self._make_task(f, True)
            if f["signal"] != 0 or f["interval"] <= 0:
                f["oneshot"] = self._make_task(f, False)
                if f["signal"] != 0:
                    self.loop.add_signal_handler(
                        f["signal"], lambda w=f["oneshot"]: asyncio.create_task(w())
                    )

    def _make_task(self, field, long_running):
        async def task():
            while True:
                field["output"] = await self._run(field["cmd"])
                await self._refresh()
                if not long_running:
                    break
                assert field["interval"] > 0
                await asyncio.sleep(field["interval"])

        return task

    async def _run(self, cmd):
        pp = asyncio.subprocess.PIPE
        proc = await asyncio.create_subprocess_shell(cmd, stdout=pp, stderr=pp)
        out, err = await proc.communicate()
        if proc.returncode == 0:
            return out.decode()
        else:
            print(f"error: {err} \nreturn: {proc.returncode}")
            return NOT_AVAILABLE

    async def _refresh(self):
        res = "  ".join(
            [
                o.get("name", "") + o.get("output", NOT_AVAILABLE).strip()
                for o in self.fields
            ]
        )
        cmd = f'xsetroot -name "{res}"'
        await self._run(cmd)


    async def check_dwm(self):
        # monitor dwm process id, if dwm is not running, exit
        while True:
            try:
                os.kill(self.ppid, 0)
            except OSError:
                sys.exit()
            await asyncio.sleep(1)


    async def main(self):
        tasks = [asyncio.create_task(self.check_dwm())]
        for f in self.fields:
            if f.get("longrunning"):
                tasks.append(asyncio.create_task(f["longrunning"]()))
            elif f.get("oneshot"):
                tasks.append(asyncio.create_task(f["oneshot"]()))

        await asyncio.gather(*tasks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="dbar")
    parser.add_argument(
        "--pid",
        dest="pid",
        action="store_true",
        default=False,
        help="If specified, the program will generate a pid file under /tmp",
    )
    args = parser.parse_args()
    pid = os.getpid()
    if args.pid:
        try:
            with open(PID_FILE, "w") as f:
                f.truncate()
                f.write(str(pid))
        except:
            pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bar = DWMStatusBar(fields_cfg, loop)
    loop.run_until_complete(bar.main())
